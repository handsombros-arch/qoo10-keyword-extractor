"""상품 단위 추천 리포트 API.

1. /collect — 관심 키워드 리스트를 받아 네이버/큐텐 스크래핑 (백그라운드)
2. /report  — DB에 수집된 상품을 조합해 마진 기반 추천 리포트 생성
"""
import asyncio
import math
import re
import traceback
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.db.connection import async_session, get_session
from app.db.models import DomesticProduct, Keyword, Qoo10Product
from app.db.sqlite_repo import SQLiteProductRepository
from app.scrapers.m08_naver import NaverShoppingScraper
from app.scrapers.m09_qoo10_products import Qoo10ProductScraper
from app.scrapers.m13_shop_products import Qoo10ShopScraper
from app.services.margin_calculator import (
    analyze_compositions,
    calculate_qoo10_margin,
    margin_verdict,
    recommend_best_composition,
)
from app.services.task_manager import task_manager
from app.services.translation import translate_papago

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


# ─── 자동 소싱 (키워드→큐텐 상품 자동 수집) ──────────

class AutoSheetRequest(BaseModel):
    mode: Literal["interest", "auto"] = "auto"
    min_search_volume: int = 300
    min_kr_ratio: float = 0.10
    max_kr_ratio: float = 0.70
    min_competition: float = 0.5
    max_competition: float = 20.0
    brand_filter: Literal["all", "general", "brand"] = "general"
    keywords_limit: int = 20
    products_per_keyword: int = 5
    # 카테고리: 빈 리스트면 전체. 리스트에 담긴 카테고리만 포함.
    categories: list[str] = Field(default_factory=list)
    # mode=interest 일 때만
    interest_keywords: list[str] = Field(default_factory=list)


def _is_brand_keyword(jp: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9\s\-_.&'+]+", jp or ""))


async def _score_keywords_for_auto(req: AutoSheetRequest) -> list[dict]:
    """필터 통과 키워드 + 추천점수 상세 리스트 반환 (keywords_limit 적용 전)."""
    if req.mode == "interest":
        # interest 모드: DB에서 관심 키워드만 뽑아 점수 계산. 필터는 적용하지 않음.
        from app.db.models import Keyword
        interest = set(req.interest_keywords or [])
        if not interest:
            return []
        async with async_session() as session:
            stmt = select(Keyword).where(Keyword.keyword_jp.in_(interest))
            result = await session.execute(stmt)
            rows = result.scalars().all()

        by_jp: dict[str, dict] = {}
        for r in rows:
            jp = r.keyword_jp
            if not jp:
                continue
            sv = r.search_volume_weekly or 0
            total = r.total_products or 0
            kr = r.products_kr or 0
            comp = r.competition_intensity or 0
            kr_ratio = (kr / total) if total > 0 else 0.0
            existing = by_jp.get(jp)
            if existing and existing["search_volume"] >= sv:
                continue
            by_jp[jp] = {
                "keyword_jp": jp,
                "search_volume": sv,
                "kr_ratio": kr_ratio,
                "competition_intensity": comp,
            }
        scored = []
        for kw in by_jp.values():
            sv = max(kw["search_volume"], 1)
            comp = max(kw["competition_intensity"], 0.1)
            kw["score"] = math.log10(sv + 1) * kw["kr_ratio"] / comp
            scored.append(kw)
        # DB에 없는 관심 키워드도 score=0으로 노출
        for kw_jp in interest - set(by_jp.keys()):
            scored.append({
                "keyword_jp": kw_jp, "search_volume": 0,
                "kr_ratio": 0.0, "competition_intensity": 0.0, "score": 0.0,
            })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    from app.db.models import Keyword

    async with async_session() as session:
        result = await session.execute(select(Keyword))
        rows = result.scalars().all()

    cat_set = set(req.categories) if req.categories else None

    by_jp: dict[str, dict] = {}
    for r in rows:
        jp = r.keyword_jp
        if not jp:
            continue
        if cat_set is not None and r.category not in cat_set:
            continue

        sv = r.search_volume_weekly or 0
        total = r.total_products or 0
        kr = r.products_kr or 0
        comp = r.competition_intensity or 0
        kr_ratio = (kr / total) if total > 0 else 0.0

        existing = by_jp.get(jp)
        if existing and existing["search_volume"] >= sv:
            continue
        by_jp[jp] = {
            "keyword_jp": jp,
            "search_volume": sv,
            "kr_ratio": kr_ratio,
            "competition_intensity": comp,
        }

    filtered = []
    for kw in by_jp.values():
        if kw["search_volume"] < req.min_search_volume:
            continue
        if kw["kr_ratio"] < req.min_kr_ratio or kw["kr_ratio"] > req.max_kr_ratio:
            continue
        c = kw["competition_intensity"]
        if c < req.min_competition or c > req.max_competition:
            continue
        brand = _is_brand_keyword(kw["keyword_jp"])
        if req.brand_filter == "general" and brand:
            continue
        if req.brand_filter == "brand" and not brand:
            continue

        sv = max(kw["search_volume"], 1)
        comp = max(kw["competition_intensity"], 0.1)
        kw["score"] = math.log10(sv + 1) * kw["kr_ratio"] / comp
        filtered.append(kw)

    filtered.sort(key=lambda x: x["score"], reverse=True)
    return filtered


async def _select_keywords_for_auto(req: AutoSheetRequest) -> list[str]:
    """추천점수 기반 키워드 선정. 모드 interest면 사용자 지정 리스트 그대로."""
    if req.mode == "interest":
        return (req.interest_keywords or [])[: req.keywords_limit]
    scored = await _score_keywords_for_auto(req)
    return [kw["keyword_jp"] for kw in scored[: req.keywords_limit]]


@router.post("/auto-sheet/preview")
async def auto_sheet_preview(req: AutoSheetRequest):
    """실제 수집 전 선정될 키워드 + 점수 상세 미리보기."""
    scored = await _score_keywords_for_auto(req)
    limited = scored[: req.keywords_limit]
    return {
        "selected_keywords": [kw["keyword_jp"] for kw in limited],
        "count": len(limited),
        "scored": limited,
        "total_candidates": len(scored),  # 필터 통과 전체 (limit 적용 전)
    }


@router.post("/auto-sheet")
async def auto_sheet(req: AutoSheetRequest):
    """필터로 키워드 선정 후 각 키워드의 큐텐 상품을 백그라운드 수집."""
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다. /auth 에서 로그인하세요."}

    selected = await _select_keywords_for_auto(req)
    if not selected:
        return {"error": "조건에 맞는 키워드가 없습니다.", "selected_keywords": [], "total": 0}

    task_id = task_manager.create_task(
        f"자동 소싱 ({len(selected)}개 키워드)", len(selected)
    )
    task_manager.start_task(task_id)

    async def _run():
        try:
            for idx, kw_jp in enumerate(selected, start=1):
                task_manager.update_progress(
                    task_id, 0, f"[{idx}/{len(selected)}] 큐텐 검색: {kw_jp}"
                )
                try:
                    scraper = Qoo10ProductScraper(browser_manager, task_manager)
                    result = await scraper.run(keyword=kw_jp)
                    products = (result.get("products") or [])[: req.products_per_keyword]
                    if products:
                        async with async_session() as s2:
                            repo = SQLiteProductRepository(s2)
                            await repo.save_qoo10_products(products)
                    task_manager.update_progress(
                        task_id, 1, f"[{idx}/{len(selected)}] {kw_jp} {len(products)}건 저장"
                    )
                except Exception:
                    traceback.print_exc()
                    task_manager.update_progress(task_id, 1, f"{kw_jp}: 실패")
            task_manager.complete_task(task_id, f"{len(selected)}개 키워드 수집 완료")
        except Exception as e:
            traceback.print_exc()
            task_manager.fail_task(task_id, f"실패: {e}")

    asyncio.create_task(_run())
    return {
        "status": "started",
        "task_id": task_id,
        "selected_keywords": selected,
        "total": len(selected),
    }


class FetchByKeywordsRequest(BaseModel):
    keywords_jp: list[str]
    per_keyword_limit: int = 5


@router.post("/qoo10-products-by-keywords")
async def qoo10_products_by_keywords(req: FetchByKeywordsRequest):
    """여러 키워드의 큐텐 상품을 최근 수집분 기준으로 한 번에 조회."""
    results: dict[str, list[dict]] = {}
    async with async_session() as session:
        for kw in req.keywords_jp:
            stmt = (
                select(Qoo10Product)
                .where(Qoo10Product.search_keyword == kw)
                .order_by(desc(Qoo10Product.lookup_date), desc(Qoo10Product.id))
                .limit(req.per_keyword_limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            products = []
            for r in rows:
                p = {c.name: getattr(r, c.name) for c in Qoo10Product.__table__.columns}
                ld = p.get("lookup_date")
                if ld is not None and not isinstance(ld, str):
                    p["lookup_date"] = str(ld)
                products.append(p)
            results[kw] = products
    return {"results": results}


# ─── 샵 벤치마크 ────────────────────────────────────

class ShopBenchmarkRequest(BaseModel):
    shop_urls: list[str] = Field(..., description="샵 URL 또는 shop_id 리스트")
    limit_per_shop: int = Field(30, description="샵당 최대 상품 수")
    sort_type: str = Field("ranking", description="ranking/review/new/price_high/price_low")


@router.post("/from-shop")
async def from_shop(req: ShopBenchmarkRequest):
    """지정 샵들에서 순위순 상위 상품 수집. DB에는 저장하지 않고 결과만 반환."""
    # 브라우저 준비 (쿠키 복원 자동)
    try:
        await browser_manager.get_page()
    except Exception as e:
        return {"error": f"브라우저 준비 실패: {e}"}

    results = []
    for shop_url in req.shop_urls:
        scraper = Qoo10ShopScraper(browser_manager, task_manager)
        try:
            res = await scraper.run(shop_url=shop_url, limit=req.limit_per_shop, sort_type=req.sort_type)
        except Exception as e:
            traceback.print_exc()
            results.append({
                "shop_id": shop_url.rstrip("/").rsplit("/", 1)[-1],
                "shop_url": shop_url,
                "products": [],
                "error": f"{type(e).__name__}: {e}",
            })
            continue

        products = res.get("products") or []
        for p in products:
            ld = p.get("lookup_date")
            if ld is not None and not isinstance(ld, str):
                p["lookup_date"] = str(ld)
        results.append({
            "shop_id": res.get("shop_id"),
            "shop_url": res.get("shop_url") or shop_url,
            "products": products,
            "error": res.get("error"),
            "debug": res.get("debug"),
        })
    return {"results": results}


# ─── 수집 ───────────────────────────────────────────

class CollectRequest(BaseModel):
    keywords_jp: list[str] = Field(..., description="수집할 일본어 키워드")
    include_naver: bool = True
    include_qoo10: bool = True


@router.post("/collect")
async def collect(req: CollectRequest):
    """백그라운드로 각 키워드에 대해 네이버(한글)·큐텐(일본어) 스크래핑.

    진행률은 task_manager 통해 /api/tasks/{task_id} 로 확인 가능.
    """
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다. 먼저 /auth 에서 로그인하세요."}

    # Keyword DB에서 한국어 매핑 확보
    jp_to_ko: dict[str, str] = {}
    async with async_session() as session:
        stmt = select(Keyword.keyword_jp, Keyword.keyword_kr).where(
            Keyword.keyword_jp.in_(req.keywords_jp)
        )
        result = await session.execute(stmt)
        for jp, ko in result.all():
            if ko and jp not in jp_to_ko:
                jp_to_ko[jp] = ko

    # 진행률: 각 키워드당 (큐텐 1 + 네이버 1) step
    steps_per_kw = int(req.include_qoo10) + int(req.include_naver)
    total_steps = len(req.keywords_jp) * max(steps_per_kw, 1)
    task_id = task_manager.create_task(
        f"상품 수집 ({len(req.keywords_jp)}개 키워드)", total_steps
    )
    task_manager.start_task(task_id)

    async def _run():
        try:
            for idx, kw_jp in enumerate(req.keywords_jp, start=1):
                kw_ko = jp_to_ko.get(kw_jp)
                if not kw_ko:
                    try:
                        kw_ko = await translate_papago(kw_jp, source="ja", target="ko")
                    except Exception:
                        kw_ko = kw_jp

                # Qoo10 (일본어)
                if req.include_qoo10:
                    task_manager.update_progress(
                        task_id, 0, f"[{idx}/{len(req.keywords_jp)}] 큐텐 수집: {kw_jp}"
                    )
                    try:
                        qoo10 = Qoo10ProductScraper(browser_manager, task_manager)
                        qres = await qoo10.run(keyword=kw_jp)
                        products = qres.get("products") or []
                        if products:
                            async with async_session() as s2:
                                repo = SQLiteProductRepository(s2)
                                await repo.save_qoo10_products(products)
                        task_manager.update_progress(
                            task_id, 1, f"[{idx}/{len(req.keywords_jp)}] 큐텐 {len(products)}건 저장"
                        )
                    except Exception:
                        traceback.print_exc()
                        task_manager.update_progress(task_id, 1, f"큐텐 실패: {kw_jp}")

                # Naver (한국어)
                if req.include_naver and kw_ko:
                    task_manager.update_progress(
                        task_id, 0, f"[{idx}/{len(req.keywords_jp)}] 네이버 수집: {kw_ko}"
                    )
                    try:
                        naver = NaverShoppingScraper(browser_manager, task_manager)
                        nres = await naver.run(keyword=kw_ko)
                        products = nres.get("products") or []
                        if products:
                            async with async_session() as s2:
                                repo = SQLiteProductRepository(s2)
                                await repo.save_domestic_products(products)
                        task_manager.update_progress(
                            task_id, 1, f"[{idx}/{len(req.keywords_jp)}] 네이버 {len(products)}건 저장"
                        )
                    except Exception:
                        traceback.print_exc()
                        task_manager.update_progress(task_id, 1, f"네이버 실패: {kw_ko}")

            task_manager.complete_task(task_id, f"{len(req.keywords_jp)}개 키워드 수집 완료")
        except Exception as e:
            traceback.print_exc()
            task_manager.fail_task(task_id, f"실패: {e}")

    asyncio.create_task(_run())
    return {
        "status": "started",
        "task_id": task_id,
        "total_keywords": len(req.keywords_jp),
        "total_steps": total_steps,
    }


# ─── 리포트 ─────────────────────────────────────────

class ReportRequest(BaseModel):
    keywords_jp: list[str]
    # 마진 계산용 기본 가정값
    default_weight_g: float = Field(300, description="실제 무게 모를 때 가정")
    default_packaging_krw: float = Field(2500, description="KSE까지 배송+포장비 가정")
    exchange_rate: float = 9.5
    use_exact_rate: bool = False
    # 추천 정렬 옵션
    min_margin_rate: float = Field(0.0, description="이 마진율 미만은 제외")
    limit: int = 50


def _score(margin_rate: float, search_volume: int, kr_ratio: float, qoo10_count: int) -> float:
    """추천 점수.

    요소:
    - margin_rate: 높을수록 좋음 (핵심)
    - search_volume: 로그 스케일 (시장 크기)
    - kr_ratio: 한국비율 (수요 검증, 0~1)
    - qoo10_count: 경쟁 수 (적을수록 좋음)
    """
    import math
    sv = max(search_volume, 1)
    comp = max(qoo10_count, 1)
    return (margin_rate) * math.log10(sv + 1) * (kr_ratio + 0.1) / math.log10(comp + 1)


@router.post("/report")
async def report(req: ReportRequest, session: AsyncSession = Depends(get_session)):
    """수집된 데이터 기반 상품 단위 추천 리포트."""
    # 1) Keyword 메타 수집
    kws = {}
    result = await session.execute(
        select(Keyword).where(Keyword.keyword_jp.in_(req.keywords_jp))
    )
    for row in result.scalars().all():
        # 같은 키워드가 여러 카테고리에 걸쳐 있을 수 있으므로 최고값 유지
        jp = row.keyword_jp
        sw = row.search_volume_weekly or 0
        tot = row.total_products or 0
        kr = row.products_kr or 0
        if jp not in kws or sw > kws[jp]["search_volume"]:
            kws[jp] = {
                "keyword_jp": jp,
                "keyword_kr": row.keyword_kr,
                "search_volume": sw,
                "total_products": tot,
                "products_kr": kr,
                "kr_ratio": (kr / tot) if tot > 0 else 0,
                "competition_intensity": row.competition_intensity or 0,
            }

    items = []

    for jp in req.keywords_jp:
        meta = kws.get(jp, {"keyword_jp": jp, "keyword_kr": None,
                            "search_volume": 0, "kr_ratio": 0,
                            "total_products": 0, "products_kr": 0,
                            "competition_intensity": 0})

        # 2) 큐텐 상품 통계 (판매가 후보) — set_count 단가 환산.
        # price_jpy / set_count → 한국 단일 가격과 동일 단위로 비교.
        unit_price = Qoo10Product.price_jpy * 1.0 / func.nullif(Qoo10Product.set_count, 0)
        q = await session.execute(
            select(
                func.count(Qoo10Product.id),
                func.min(unit_price),
                func.avg(unit_price),
                func.max(unit_price),
                func.avg(Qoo10Product.set_count),  # 참고용 평균 묶음
            ).where(Qoo10Product.search_keyword == jp, Qoo10Product.price_jpy > 0)
        )
        qoo10_count, qoo10_min_jpy, qoo10_avg_jpy, qoo10_max_jpy, qoo10_avg_set = q.one()
        qoo10_count = qoo10_count or 0

        # 3) 국내 매칭 한국 상품 (구매가 후보)
        #    우선순위: ① DomesticMatchCandidate.decision='accepted' (Phase 1 결합 룰)
        #              ② 없으면 같은 keyword_kr 단순 최저가 (legacy)
        #    옵션 정보 (DomesticProductOption) 도 같이 조회.
        from app.db.models import DomesticMatchCandidate as _DMC, DomesticProductOption as _DPO

        kw_ko = meta["keyword_kr"] or ""
        cheapest_domestic = None
        match_source = None

        # ① 매칭된 한국 상품 (큐텐 jp → DMC.qid → 한국 dp)
        r = (await session.execute(
            select(DomesticProduct)
            .join(_DMC, _DMC.domestic_product_id == DomesticProduct.id)
            .join(Qoo10Product, Qoo10Product.id == _DMC.qoo10_product_id)
            .where(Qoo10Product.search_keyword == jp)
            .where(_DMC.decision == "accepted")
            .where(DomesticProduct.price_krw > 0)
            .order_by(DomesticProduct.price_krw.asc())
            .limit(1)
        )).scalar_one_or_none()
        if r:
            match_source = "matched"

        # ② legacy fallback
        if r is None and kw_ko:
            r = (await session.execute(
                select(DomesticProduct)
                .where(DomesticProduct.search_keyword == kw_ko, DomesticProduct.price_krw > 0)
                .order_by(DomesticProduct.price_krw.asc())
                .limit(1)
            )).scalar_one_or_none()
            if r:
                match_source = "cheapest"

        if r:
            opt_rows = (await session.execute(
                select(_DPO.option_name, _DPO.option_price_krw, _DPO.in_stock)
                .where(_DPO.domestic_product_id == r.id)
                .order_by(_DPO.option_price_krw.asc().nullslast())
            )).all()
            cheapest_domestic = {
                "id": r.id,
                "source": r.source,
                "product_name": r.product_name,
                "price_krw": r.price_krw,
                "product_url": r.product_url,
                "cover_image_url": r.cover_image_url,
                "match_source": match_source,
                "shipping_kind": r.shipping_kind,
                "shipping_amount": r.shipping_amount,
                "shipping_threshold": r.shipping_threshold,
                "options": [
                    {"name": on or "default", "price_krw": op, "in_stock": bool(ist)}
                    for on, op, ist in opt_rows
                ],
            }

        # 4) 마진 계산 (국내 최저가를 구매가로, 큐텐 평균가를 판매가로 가정)
        margin = None
        compositions_summary = None
        if cheapest_domestic and qoo10_avg_jpy:
            purchase_krw = float(cheapest_domestic["price_krw"])
            sell_jpy = float(qoo10_avg_jpy)

            m = calculate_qoo10_margin(
                weight_g=req.default_weight_g,
                purchase_price_krw=purchase_krw,
                shipping_packaging_krw=req.default_packaging_krw,
                sell_price_jpy=sell_jpy,
                exchange_rate=req.exchange_rate,
                use_exact_rate=req.use_exact_rate,
                shipping_mode="auto",
            )
            margin = {
                "profit_krw": m.profit_krw,
                "margin_rate": m.margin_rate,
                "verdict": margin_verdict(m.margin_rate),
                "shipping_mode": m.shipping_mode_resolved,
                "sell_price_jpy": sell_jpy,
                "purchase_price_krw": purchase_krw,
            }

            # 마진이 애매/부족이면 구성 분석
            if m.margin_rate < 0.20:
                comps = analyze_compositions(
                    weight_g=req.default_weight_g,
                    purchase_price_krw=purchase_krw,
                    shipping_packaging_krw=req.default_packaging_krw,
                    sell_price_jpy=sell_jpy,
                    exchange_rate=req.exchange_rate,
                    use_exact_rate=req.use_exact_rate,
                    shipping_mode="auto",
                )
                best = recommend_best_composition(comps)
                compositions_summary = {
                    "best_label": best.composition_label,
                    "best_margin_rate": best.margin_rate,
                    "best_profit_krw": best.profit_krw,
                    "improvement": best.margin_rate - m.margin_rate,
                }

        # 점수
        margin_rate_for_score = (margin or {}).get("margin_rate", 0) or 0
        score = _score(
            margin_rate=margin_rate_for_score,
            search_volume=meta["search_volume"],
            kr_ratio=meta["kr_ratio"],
            qoo10_count=qoo10_count,
        )

        items.append({
            "keyword_jp": jp,
            "keyword_kr": meta["keyword_kr"],
            "search_volume": meta["search_volume"],
            "kr_ratio": meta["kr_ratio"],
            "competition_intensity": meta["competition_intensity"],
            "qoo10_stats": {
                "count": qoo10_count,
                "min_jpy": float(qoo10_min_jpy or 0),
                "avg_jpy": float(qoo10_avg_jpy or 0),
                "max_jpy": float(qoo10_max_jpy or 0),
            },
            "cheapest_domestic": cheapest_domestic,
            "margin": margin,
            "compositions": compositions_summary,
            "score": round(score, 4),
            "score_components": {
                "margin_rate": margin_rate_for_score,
                "search_volume": meta["search_volume"],
                "kr_ratio": meta["kr_ratio"],
                "qoo10_count": qoo10_count,
            },
        })

    # 최소 마진 필터
    items = [
        it for it in items
        if (it["margin"] or {}).get("margin_rate", -1) >= req.min_margin_rate
    ]
    items.sort(key=lambda x: x["score"], reverse=True)
    return {"items": items[: req.limit], "total": len(items)}


# ─── 큐텐 ↔ 한국 cover 이미지 1:1 매칭 (3-1) ─────────


@router.post("/match-images")
async def match_qoo10_to_domestic_by_image(body: dict | None = None):
    """큐텐 cover ↔ 한국 cover 이미지 비전 1:1 비교 (백그라운드).

    body:
      date:               YYYY-MM-DD (기본 오늘)
      keywords_jp:        list[str]  (선택, 큐텐 search_keyword 한정)
      per_qoo10_top_n:    int        (큐텐 1개당 비교할 한국 후보 수, 기본 3)
      threshold:          float      (이미지 accepted 임계값, 기본 IMAGE_MATCH_THRESHOLD env → 0.7)
      text_threshold:     float      (텍스트 accepted 임계값, 기본 TEXT_MATCH_THRESHOLD env → 0.3)
      limit:              int        (전체 비교 호출 상한)

    동작:
      - lookup_date 의 큐텐 상품 (cover_image_url 有) 대상
      - 같은 search_keyword 의 한국 상품 (image_local_path 우선, cover_image_url 폴백)
        - image_score_overall DESC, price_krw ASC 정렬 → top N
      - (qoo10_id, domestic_id) 중복은 DomesticMatchCandidate 중복 방지
      - 결합 룰: text_score ≥ text_threshold AND image_score ≥ threshold → accepted
        (어느 한쪽이라도 미달이면 rejected) — 광고 키워드 도용 자동 거부
    """
    import asyncio as _asyncio
    import os as _os
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel
    from app.db.models import (
        Qoo10Product as _Q, DomesticProduct as _DP, Keyword as _K,
        DomesticMatchCandidate as _DMC,
    )

    body = body or {}
    raw_date = body.get("date")
    if raw_date:
        try:
            target_date = _dt.strptime(str(raw_date), "%Y-%m-%d").date()
        except ValueError:
            return {"error": "date 형식: YYYY-MM-DD"}
    else:
        target_date = _date_cls.today()

    keywords_jp = body.get("keywords_jp") or []
    top_n = int(body.get("per_qoo10_top_n", 3))
    raw_thr = body.get("threshold")
    if raw_thr is not None:
        threshold = float(raw_thr)
    else:
        try:
            threshold = float(_os.getenv("IMAGE_MATCH_THRESHOLD", "0.7"))
        except ValueError:
            threshold = 0.7
    raw_text_thr = body.get("text_threshold")
    if raw_text_thr is not None:
        text_threshold = float(raw_text_thr)
    else:
        try:
            text_threshold = float(_os.getenv("TEXT_MATCH_THRESHOLD", "0.3"))
        except ValueError:
            text_threshold = 0.3
    raw_limit = body.get("limit")
    overall_limit = int(raw_limit) if raw_limit else None

    # search_keyword 화이트리스트 (jp → kr 매핑)
    search_jp_filter: list[str] | None = list(keywords_jp) if keywords_jp else None

    # 1) 큐텐 후보 — product_name_ko 도 함께 (텍스트 매칭용)
    async with async_session() as session:
        q_stmt = (
            _sel(_Q.id, _Q.product_name, _Q.product_name_ko,
                 _Q.cover_image_url, _Q.search_keyword)
            .where(_Q.lookup_date == target_date)
            .where(_Q.cover_image_url.is_not(None))
        )
        if search_jp_filter:
            q_stmt = q_stmt.where(_Q.search_keyword.in_(search_jp_filter))
        q_rows = (await session.execute(q_stmt)).all()

        # 2) jp → kr 매핑 (q_rows 인덱스: 0=id 1=name 2=name_ko 3=cover_url 4=search_kw)
        # ① keywords (legacy) — keyword_jp == search_keyword
        # ② expanded_keywords (Phase 1-D) — parent_jp == search_keyword (1:N)
        # 하나의 jp 에 여러 kr 후보가 있을 수 있도록 1:N dict.
        from app.db.models import ExpandedKeyword as _EK

        unique_jp = sorted({r[4] for r in q_rows if r[4]})
        kr_map: dict[str, list[str]] = {}
        repr_kr: dict[str, str] = {}  # jp 별 대표 kr (legacy 우선) — pairs 의 qkw_kr 에 사용
        if unique_jp:
            # ① legacy keywords
            kr_rows = await session.execute(
                _sel(_K.keyword_jp, _K.keyword_kr).where(_K.keyword_jp.in_(unique_jp))
                .where(_K.keyword_kr.is_not(None))
            )
            for jp, kr in kr_rows.all():
                if jp and kr:
                    kr_map.setdefault(jp, []).append(kr)
                    repr_kr.setdefault(jp, kr)

            # ② expanded_keywords (parent_jp 기준)
            ek_rows = await session.execute(
                _sel(_EK.parent_jp, _EK.keyword_kr).where(_EK.parent_jp.in_(unique_jp))
                .where(_EK.keyword_kr.is_not(None))
                .where(_EK.keyword_kr != "")
            )
            for pjp, kr in ek_rows.all():
                if pjp and kr and kr not in kr_map.get(pjp, []):
                    kr_map.setdefault(pjp, []).append(kr)
                    repr_kr.setdefault(pjp, kr)

        # 3) 한국 후보 — 같은 search_keyword(kr) 의 top N (product_name 도 같이)
        all_kr_list: list[str] = []
        for vs in kr_map.values():
            all_kr_list.extend(vs)
        unique_kr = sorted(set(all_kr_list))
        kr_to_candidates: dict[str, list[tuple[int, str | None, str | None, str | None]]] = {}
        if unique_kr:
            # 한국 후보 검색 — target_date 우선, 없으면 같은 search_keyword 의 가장 최근 행.
            # expanded keyword 검색은 다른 날짜에 진행될 수 있어 lookup_date 제한 풀어둠.
            d_stmt = (
                _sel(_DP.id, _DP.product_name, _DP.search_keyword,
                     _DP.image_local_path, _DP.cover_image_url,
                     _DP.image_score_overall, _DP.price_krw, _DP.lookup_date)
                .where(_DP.search_keyword.in_(unique_kr))
                .order_by(_DP.lookup_date.desc(), _DP.id.desc())
            )
            d_rows = (await session.execute(d_stmt)).all()
            # 한 search_keyword 당 같은 id 중복 방지 (lookup_date 다른 동일 상품 케이스)
            tmp: dict[str, list] = {}
            seen_ids: set[int] = set()
            for did, dname, dkw, lp, cu, sc, pk, _ld in d_rows:
                if not dkw or did in seen_ids:
                    continue
                if not (lp or cu):
                    continue
                seen_ids.add(did)
                tmp.setdefault(dkw, []).append((did, dname, lp, cu, sc or 0.0, pk or 10**9))
            for dkw, lst in tmp.items():
                lst.sort(key=lambda r: (-r[4], r[5]))  # image_score DESC, price ASC
                kr_to_candidates[dkw] = [
                    (did, dname, lp, cu) for did, dname, lp, cu, _, _ in lst[:top_n]
                ]

        # 4) 이미 비교된 (qoo10_id, domestic_id) 중복 방지
        existing_pairs: set[tuple[int, int]] = set()
        ex_rows = await session.execute(
            _sel(_DMC.qoo10_product_id, _DMC.domestic_product_id)
        )
        for qid, did in ex_rows.all():
            if qid is not None and did is not None:
                existing_pairs.add((qid, did))

    # 5) 비교 작업 리스트 — 큐텐(jp/ko/cover/kw_kr) + 한국(name/lp/cu)
    # 큐텐 1개 → 매핑된 모든 keyword_kr (legacy + expanded) 의 한국 후보 풀에서 선정.
    # qkw_kr 은 대표 kr (legacy 우선) — 텍스트 매칭 토큰 보너스에 사용.
    pairs: list[dict] = []
    for qid, qname, qko, qurl, qjp in q_rows:
        kr_list = kr_map.get(qjp or "", [])
        if not kr_list:
            continue
        rep_kr = repr_kr.get(qjp or "", kr_list[0])
        # 한 큐텐 상품 → 모든 매핑 kr 의 한국 후보 합침
        # 같은 (qid, did) pair 가 여러 kw_kr (legacy + expanded) 경유로 중복 방지
        for kw_kr in kr_list:
            for did, dname, dlp, dcu in kr_to_candidates.get(kw_kr, []):
                if (qid, did) in existing_pairs:
                    continue
                pairs.append({
                    "qid": qid, "qname": qname, "qko": qko, "qurl": qurl,
                    "qkw_kr": rep_kr,
                    "did": did, "dname": dname, "dlp": dlp, "dcu": dcu,
                })
                existing_pairs.add((qid, did))
                if overall_limit and len(pairs) >= overall_limit:
                    break
            if overall_limit and len(pairs) >= overall_limit:
                break
        if overall_limit and len(pairs) >= overall_limit:
            break

    if not pairs:
        return {
            "task_id": None, "candidates": 0, "scanned_qoo10": len(q_rows),
            "message": f"{target_date}: 비교할 후보 0건",
        }

    task_id = task_manager.create_task(
        name=f"이미지+텍스트 매칭 ({target_date}, img≥{threshold:.2f} txt≥{text_threshold:.2f})",
        total=len(pairs),
    )
    _asyncio.create_task(_run_match_images(task_id, pairs, threshold, text_threshold))
    return {
        "task_id": task_id, "candidates": len(pairs),
        "scanned_qoo10": len(q_rows),
        "threshold": threshold, "text_threshold": text_threshold,
        "date": str(target_date),
    }


async def _run_match_images(
    task_id: str, pairs: list[dict],
    img_threshold: float, text_threshold: float,
) -> None:
    """백그라운드 — 각 (qoo10, domestic) 쌍 cover 비교 + DomesticMatchCandidate INSERT.

    결합 룰: text_score >= text_threshold AND image_score >= img_threshold → accepted.
    어느 한쪽이라도 미달이면 rejected (광고 키워드 도용 자동 거부).
    """
    from pathlib import Path as _P
    from app.db.models import DomesticMatchCandidate as _DMC
    from app.services.domestic_image_pipeline import download_to_temp, IMAGE_ROOT
    from app.services.llm.image_match import compare_two_images_async
    from app.services.llm.text_match import name_similarity

    # image_local_path 가 'image/...' 같은 상대경로로 저장돼 있어도 안전하게 절대경로로.
    # 백엔드 cwd 가 프로젝트 루트가 아닐 때(IDE/서비스 실행 등) 발생하던 FileNotFoundError 회피.
    _PROJECT_ROOT = IMAGE_ROOT.parent

    def _abs_path(p: str | None) -> str | None:
        if not p:
            return None
        path = _P(p)
        if not path.is_absolute():
            path = (_PROJECT_ROOT / p).resolve()
        return str(path) if path.exists() else None

    task_manager.start_task(task_id)
    accepted = rejected = failed = 0

    try:
        for idx, p in enumerate(pairs, 1):
            qid, did = p["qid"], p["did"]

            # 큐텐 cover — URL 만 있어 매번 다운로드
            q_tmp = await download_to_temp(p["qurl"]) if p["qurl"] else None
            # 한국 cover — image_local_path 있으면 그거 (절대경로 변환), 없으면 URL 다운
            d_tmp = None
            d_path = _abs_path(p["dlp"])
            if not d_path and p["dcu"]:
                d_tmp = await download_to_temp(p["dcu"])
                d_path = d_tmp

            if not q_tmp or not d_path:
                failed += 1
                if q_tmp:
                    try: _P(q_tmp).unlink(missing_ok=True)
                    except Exception: pass
                if d_tmp:
                    try: _P(d_tmp).unlink(missing_ok=True)
                    except Exception: pass
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(pairs)}] 다운로드 실패 q={qid} d={did}",
                )
                continue

            # 텍스트 매칭 — LLM 호출 없는 순수 토큰 자카드
            # 큐텐 측 텍스트에 keyword_kr (브랜드 토큰) 합쳐서 번역 누락 회피.
            # 예: 「コスノリ 眉毛脱色」 ko 「이지브로우 톤체인지」 + kw_kr 「코스노리 눈썹 탈색」
            #     → 한국 「코스노리 이지 브로우 톤 체인저」 와 「코스노리/이지브로우/톤」 토큰 일치.
            qko = (p.get("qko") or p.get("qname") or "").strip()
            qkw = (p.get("qkw_kr") or "").strip()
            q_text_for_match = (qko + " " + qkw).strip() if qkw else qko
            d_text_for_match = (p.get("dname") or "").strip()
            try:
                text_score = name_similarity(q_text_for_match, d_text_for_match)
            except Exception:
                text_score = 0.0

            try:
                res = await compare_two_images_async(q_tmp, d_path)
                score = float(res.get("score") or 0.0)
                note = str(res.get("note") or "")
                ok = bool(res.get("ok"))
            except Exception as e:
                failed += 1
                score = 0.0; note = f"ERR: {e}"; ok = False
            finally:
                try: _P(q_tmp).unlink(missing_ok=True)
                except Exception: pass
                if d_tmp:
                    try: _P(d_tmp).unlink(missing_ok=True)
                    except Exception: pass

            # 결합 룰: 양쪽 모두 임계값 통과 + 비전 호출 ok
            decision = (
                "accepted"
                if (ok and score >= img_threshold and text_score >= text_threshold)
                else "rejected"
            )
            if decision == "accepted":
                accepted += 1
            else:
                rejected += 1

            try:
                async with async_session() as session:
                    session.add(_DMC(
                        qoo10_product_id=qid,
                        domestic_product_id=did,
                        source_match_kind="keyword",
                        name_score=text_score,
                        image_score=score,
                        image_match_note=note,
                        decision=decision,
                    ))
                    await session.commit()
            except Exception as e:
                failed += 1

            task_manager.update_progress(
                task_id, increment=1,
                message=(
                    f"[{idx}/{len(pairs)}] {decision[:3]} "
                    f"txt={text_score:.2f} img={score:.2f} "
                    f"q={qid} d={did} {note[:20]}"
                ),
            )

        task_manager.complete_task(
            task_id,
            message=(
                f"완료 — accepted {accepted}, rejected {rejected}, failed {failed} "
                f"(쌍 {len(pairs)})"
            ),
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()
