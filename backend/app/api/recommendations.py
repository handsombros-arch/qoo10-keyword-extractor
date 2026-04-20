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


async def _select_keywords_for_auto(req: AutoSheetRequest) -> list[str]:
    """추천점수 기반 키워드 선정. 모드 interest면 사용자 지정 리스트 그대로."""
    if req.mode == "interest":
        return (req.interest_keywords or [])[: req.keywords_limit]

    from app.db.models import Keyword

    async with async_session() as session:
        result = await session.execute(select(Keyword))
        rows = result.scalars().all()

    # 카테고리 필터링
    cat_set = set(req.categories) if req.categories else None

    # 같은 keyword_jp 중 가장 큰 검색량만 유지 (단 카테고리는 누적)
    by_jp: dict[str, dict] = {}
    for r in rows:
        jp = r.keyword_jp
        if not jp:
            continue
        # 카테고리 필터 (지정된 카테고리 중 하나라도 일치하면 통과)
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

    # 필터
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

        # 추천점수
        sv = max(kw["search_volume"], 1)
        comp = max(kw["competition_intensity"], 0.1)
        score = math.log10(sv + 1) * kw["kr_ratio"] / comp
        kw["_score"] = score
        filtered.append(kw)

    filtered.sort(key=lambda x: x["_score"], reverse=True)
    return [kw["keyword_jp"] for kw in filtered[: req.keywords_limit]]


@router.post("/auto-sheet/preview")
async def auto_sheet_preview(req: AutoSheetRequest):
    """실제 수집 전 선정될 키워드 미리보기."""
    selected = await _select_keywords_for_auto(req)
    return {"selected_keywords": selected, "count": len(selected)}


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

        # 2) 큐텐 상품 통계 (판매가 후보)
        q = await session.execute(
            select(
                func.count(Qoo10Product.id),
                func.min(Qoo10Product.price_jpy),
                func.avg(Qoo10Product.price_jpy),
                func.max(Qoo10Product.price_jpy),
            ).where(Qoo10Product.search_keyword == jp, Qoo10Product.price_jpy > 0)
        )
        qoo10_count, qoo10_min_jpy, qoo10_avg_jpy, qoo10_max_jpy = q.one()
        qoo10_count = qoo10_count or 0

        # 3) 국내 최저가 (구매가 후보)
        kw_ko = meta["keyword_kr"] or ""
        cheapest_domestic = None
        if kw_ko:
            d = await session.execute(
                select(DomesticProduct)
                .where(DomesticProduct.search_keyword == kw_ko, DomesticProduct.price_krw > 0)
                .order_by(DomesticProduct.price_krw.asc())
                .limit(1)
            )
            r = d.scalar_one_or_none()
            if r:
                cheapest_domestic = {
                    "source": r.source,
                    "product_name": r.product_name,
                    "price_krw": r.price_krw,
                    "product_url": r.product_url,
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
