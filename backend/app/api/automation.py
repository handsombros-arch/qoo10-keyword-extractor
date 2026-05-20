"""야간 자동화 워크플로우 전용 라우터.

엔드포인트:
- POST /api/keywords/auto-filter
    특정 일자에 수집된 Keyword 중 (검색량/한국비율/경쟁강도) 기준 통과한 것만
    점수 내림차순으로 반환.

- POST /api/recommend/auto-build
    필터링된 키워드와 그 키워드의 큐텐/쿠팡/네이버 수집 결과를 결합해
    마진까지 계산한 후 "추천 후보" 리스트를 user_data 테이블에 저장.
    프론트엔드는 건드리지 않는다 — 사용자는 다음 날 출근 후
    /recommend-products 화면에서 이 후보 리스트를 참고해 직접 시트를 빌드한다.

기존 코드 재활용:
- recommendations._is_brand_keyword
- margin_calculator.{calculate_qoo10_margin, analyze_compositions,
                    recommend_best_composition, margin_verdict}
점수 공식은 recommendations.py 와 동일한 한 줄 inline.
"""
from __future__ import annotations

import json as jsonlib
import logging
import math
import os
import uuid
from datetime import date as date_cls, datetime
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter
# HTML 뷰 (auto-collected) 폐기됨 — /review/{date} React + /recommend-products 시트가 흡수.
# RD 진단 위해서는 /api/review/{date} JSON + /api/sheet/row-meta + 로그 직접 사용.
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from app.api.recommendations import _is_brand_keyword
from app.db.connection import async_session
from app.db.models import DomesticProduct, Keyword, Qoo10Product, UserData
from app.services.margin_calculator import (
    analyze_compositions,
    calculate_qoo10_margin,
    margin_verdict,
    recommend_best_composition,
)

router = APIRouter(tags=["automation"])


# ─── /api/keywords/auto-filter ─────────────────────────

class AutoFilterRequest(BaseModel):
    competition_max: float = Field(0.5, description="이 값 이하만 통과")
    kr_ratio_min: float = Field(0.3, description="이 값 이상만 통과 (0~1)")
    search_volume_min: int = Field(100, description="주평 검색량 최소")
    date: Optional[date_cls] = Field(None, description="None이면 오늘")
    brand_filter: str = Field("all", pattern="^(all|general|brand)$",
                              description="all=모두 통과(기본), general=브랜드 제외, brand=브랜드만")
    categories: Optional[list[str]] = Field(
        None,
        description="category_inferred 화이트리스트. None 이면 모두 통과. 예: ['03.뷰티&화장품','07.식품']",
    )
    category_blacklist: Optional[list[str]] = Field(
        None,
        description="raw 큐텐 category blacklist. 예: ['05.디지털', '08.엔터테인먼트&e티켓']",
    )
    limit: int = Field(50, description="상위 N개만 반환")


@router.post("/api/keywords/auto-filter")
async def auto_filter(req: AutoFilterRequest):
    target_date = req.date or date_cls.today()

    async with async_session() as session:
        result = await session.execute(
            select(Keyword).where(Keyword.lookup_date == target_date)
        )
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
            "keyword_kr": r.keyword_kr,
            "category": r.category,
            "category_inferred": r.category_inferred or "",
            "is_brand": bool(r.is_brand),
            "brand_kr": r.brand_kr or "",
            "brand_jp": r.brand_jp or "",
            "brand_en": r.brand_en or "",
            "search_volume": sv,
            "kr_ratio": kr_ratio,
            "competition_intensity": comp,
        }

    # categories 화이트리스트 정규화 (None/빈 리스트면 모두 통과)
    cat_whitelist = set(req.categories) if req.categories else None
    # MMM-1: raw 큐텐 카테고리 blacklist (디지털/엔터테인먼트 등 제외)
    cat_blacklist = set(req.category_blacklist) if req.category_blacklist else set()

    filtered = []
    for kw in by_jp.values():
        # MMM-1: blacklist 우선 (브랜드 무관 — 디지털/엔터테인먼트는 사장님 사업 영역 X)
        if cat_blacklist and kw.get("category") in cat_blacklist:
            continue
        if kw["search_volume"] < req.search_volume_min:
            continue
        if kw["kr_ratio"] < req.kr_ratio_min:
            continue
        if kw["competition_intensity"] <= 0:
            # 경쟁강도 미측정 키워드는 신뢰 불가 → 제외
            continue
        if kw["competition_intensity"] > req.competition_max:
            continue

        # 브랜드 판별 먼저 (카테고리 화이트리스트보다 우선) —
        # 브랜드 키워드는 카테고리 분류 신뢰도가 낮아 (예: laka → 홈&생활) 화이트리스트로 누락 방지.
        is_brand = kw["is_brand"] or _is_brand_keyword(kw["keyword_jp"])
        kw["is_brand"] = bool(is_brand)
        if req.brand_filter == "general" and is_brand:
            continue
        if req.brand_filter == "brand" and not is_brand:
            continue

        # 카테고리 화이트리스트 (LLM 추론 결과 기준) — 브랜드 키워드는 무시 (자동 통과).
        if cat_whitelist is not None and not is_brand:
            if kw["category_inferred"] not in cat_whitelist:
                continue

        sv = max(kw["search_volume"], 1)
        comp = max(kw["competition_intensity"], 0.1)
        kw["score"] = round(math.log10(sv + 1) * kw["kr_ratio"] / comp, 4)
        filtered.append(kw)

    filtered.sort(key=lambda x: x["score"], reverse=True)
    limited = filtered[: req.limit]

    return {
        "date": str(target_date),
        "count": len(limited),
        "total_candidates": len(filtered),
        "keywords": limited,
    }


# ─── /api/recommend/auto-build ─────────────────────────

class AutoBuildRequest(BaseModel):
    keywords_jp: list[str]
    date: Optional[date_cls] = None
    default_weight_g: float = 300
    default_packaging_krw: float = 2500
    exchange_rate: float = 9.5
    min_margin_rate: float = Field(0.10, description="이 마진율 미만은 제외 (0~1)")
    limit: int = 30


@router.post("/api/recommend/auto-build")
async def auto_build(req: AutoBuildRequest):
    target_date = req.date or date_cls.today()
    items: list[dict] = []

    async with async_session() as session:
        # 1) 키워드 메타 (lookup_date 무관 — 같은 키워드 여러 행 중 검색량 최대 행 채택)
        meta_result = await session.execute(
            select(Keyword).where(Keyword.keyword_jp.in_(req.keywords_jp))
        )
        kw_map: dict[str, dict] = {}
        for r in meta_result.scalars().all():
            jp = r.keyword_jp
            sw = r.search_volume_weekly or 0
            total = r.total_products or 0
            kr = r.products_kr or 0
            existing = kw_map.get(jp)
            if existing and existing.get("search_volume", 0) >= sw:
                continue
            kw_map[jp] = {
                "keyword_jp": jp,
                "keyword_kr": r.keyword_kr,
                "search_volume": sw,
                "kr_ratio": (kr / total) if total > 0 else 0.0,
                "competition_intensity": r.competition_intensity or 0,
                "total_products": total,
                "products_kr": kr,
            }

        for jp in req.keywords_jp:
            meta = kw_map.get(jp, {
                "keyword_jp": jp, "keyword_kr": None,
                "search_volume": 0, "kr_ratio": 0.0,
                "competition_intensity": 0.0,
                "total_products": 0, "products_kr": 0,
            })

            # 2) 큐텐 상품 통계 (판매가 후보) — set_count 단가 환산.
            # price_jpy / set_count 로 묶음 가격을 단가로 변환 → 한국 단일 가격과 동일 단위로 비교.
            unit_price = Qoo10Product.price_jpy * 1.0 / func.nullif(Qoo10Product.set_count, 0)
            q = await session.execute(
                select(
                    func.count(Qoo10Product.id),
                    func.min(unit_price),
                    func.avg(unit_price),
                    func.max(unit_price),
                    func.avg(Qoo10Product.set_count),  # 평균 묶음 사이즈 (참고용)
                ).where(
                    Qoo10Product.search_keyword == jp,
                    Qoo10Product.price_jpy > 0,
                )
            )
            qoo10_count, qoo10_min, qoo10_avg, qoo10_max, qoo10_avg_set = q.one()
            qoo10_count = qoo10_count or 0

            # 3) 국내 매칭 한국 상품 (구매가 후보) — RRR-1 적합도 우선
            #    우선순위:
            #      ① accepted + quality_score >= QUALITY_CHEAPEST_MIN (기본 0.6) 중 최저가
            #      ② accepted 만 (quality 통과 0건 시 relax)
            #      ③ 같은 search_keyword 단순 최저가 (legacy fallback, 매칭 0건)
            #    옵션 정보 (DomesticProductOption) 도 같이 조회해서 payload 에 포함.
            from app.db.models import DomesticMatchCandidate as _DMC, DomesticProductOption as _DPO

            kw_ko = meta.get("keyword_kr") or ""
            quality_min = float(os.getenv("QUALITY_CHEAPEST_MIN", "0.6") or 0.6)
            cheapest = None

            # ① 적합도 우선 — accepted + quality_score >= 0.6 중 최저가
            row = (await session.execute(
                select(DomesticProduct)
                .join(_DMC, _DMC.domestic_product_id == DomesticProduct.id)
                .join(Qoo10Product, Qoo10Product.id == _DMC.qoo10_product_id)
                .where(Qoo10Product.search_keyword == jp)
                .where(_DMC.decision == "accepted")
                .where(_DMC.quality_score >= quality_min)
                .where(DomesticProduct.price_krw > 0)
                .order_by(DomesticProduct.price_krw.asc())
                .limit(1)
            )).scalar_one_or_none()
            match_source = "matched_high_quality" if row else None

            # ② accepted relax — quality 통과 0건이면 그냥 accepted 중 최저가
            if row is None:
                row = (await session.execute(
                    select(DomesticProduct)
                    .join(_DMC, _DMC.domestic_product_id == DomesticProduct.id)
                    .join(Qoo10Product, Qoo10Product.id == _DMC.qoo10_product_id)
                    .where(Qoo10Product.search_keyword == jp)
                    .where(_DMC.decision == "accepted")
                    .where(DomesticProduct.price_krw > 0)
                    .order_by(DomesticProduct.price_krw.asc())
                    .limit(1)
                )).scalar_one_or_none()
                if row:
                    match_source = "matched_any"

            # ③ legacy fallback — 같은 keyword_ko 단순 최저가 (매칭 0건)
            if row is None and kw_ko:
                row = (await session.execute(
                    select(DomesticProduct)
                    .where(DomesticProduct.search_keyword == kw_ko)
                    .where(DomesticProduct.price_krw > 0)
                    .order_by(DomesticProduct.price_krw.asc())
                    .limit(1)
                )).scalar_one_or_none()
                match_source = "cheapest" if row else None

            if row:
                # DomesticProductOption 조회
                opt_rows = (await session.execute(
                    select(_DPO.option_name, _DPO.option_price_krw, _DPO.in_stock)
                    .where(_DPO.domestic_product_id == row.id)
                    .order_by(_DPO.option_price_krw.asc().nullslast())
                )).all()
                cheapest = {
                    "id": row.id,
                    "source": row.source,
                    "product_name": row.product_name,
                    "price_krw": row.price_krw,
                    "product_url": row.product_url,
                    "cover_image_url": row.cover_image_url,
                    "match_source": match_source,
                    "shipping_kind": row.shipping_kind,
                    "shipping_amount": row.shipping_amount,
                    "shipping_threshold": row.shipping_threshold,
                    "options": [
                        {
                            "name": on or "default",
                            "price_krw": op,
                            "in_stock": bool(ist),
                        }
                        for on, op, ist in opt_rows
                    ],
                }

            # 4) 마진 계산 — 단품, 부족 시 구성 분석 후 최선 채택
            margin_block = None
            if cheapest and qoo10_avg:
                purchase_krw = float(cheapest["price_krw"])
                sell_jpy = float(qoo10_avg)
                base = calculate_qoo10_margin(
                    weight_g=req.default_weight_g,
                    purchase_price_krw=purchase_krw,
                    shipping_packaging_krw=req.default_packaging_krw,
                    sell_price_jpy=sell_jpy,
                    exchange_rate=req.exchange_rate,
                    shipping_mode="auto",
                )
                best = base
                if base.margin_rate < 0.20:
                    comps = analyze_compositions(
                        weight_g=req.default_weight_g,
                        purchase_price_krw=purchase_krw,
                        shipping_packaging_krw=req.default_packaging_krw,
                        sell_price_jpy=sell_jpy,
                        exchange_rate=req.exchange_rate,
                        shipping_mode="auto",
                    )
                    best = recommend_best_composition(comps)

                margin_block = {
                    "profit_krw": round(best.profit_krw, 1),
                    "margin_rate": round(best.margin_rate, 4),
                    "verdict": margin_verdict(best.margin_rate),
                    "shipping_mode": best.shipping_mode_resolved,
                    "composition": best.composition_label,
                    "sell_price_jpy": round(sell_jpy, 1),
                    "purchase_price_krw": round(purchase_krw, 1),
                }

            # 5) 마진 미달 제외
            if not margin_block or margin_block["margin_rate"] < req.min_margin_rate:
                continue

            sv = max(meta["search_volume"], 1)
            comp = max(meta["competition_intensity"], 0.1)
            kw_score = math.log10(sv + 1) * meta["kr_ratio"] / comp
            final_score = kw_score * max(margin_block["margin_rate"], 0.0) * 100

            items.append({
                "keyword_jp": jp,
                "keyword_kr": meta.get("keyword_kr"),
                "search_volume": meta["search_volume"],
                "kr_ratio": round(meta["kr_ratio"], 3),
                "competition_intensity": round(meta["competition_intensity"], 3),
                "qoo10_count": qoo10_count,
                "qoo10_avg_jpy": round(float(qoo10_avg) if qoo10_avg else 0.0, 1),
                "qoo10_min_jpy": round(float(qoo10_min) if qoo10_min else 0.0, 1),
                "qoo10_max_jpy": round(float(qoo10_max) if qoo10_max else 0.0, 1),
                "cheapest_domestic": cheapest,
                "margin": margin_block,
                "kw_score": round(kw_score, 3),
                "final_score": round(final_score, 3),
            })

    items.sort(key=lambda x: x["final_score"], reverse=True)
    limited = items[: req.limit]

    payload = {
        "date": str(target_date),
        "generated_at": datetime.utcnow().isoformat(),
        "min_margin_rate": req.min_margin_rate,
        "count": len(limited),
        "total_candidates": len(items),
        "candidates": limited,
    }

    # 6) user_data 저장 (key="last_auto_collected:{date}") — UserData 모델 직접 사용
    storage_key = f"last_auto_collected:{target_date}"
    async with async_session() as session:
        existing = await session.execute(
            select(UserData).where(UserData.key == storage_key)
        )
        row = existing.scalar_one_or_none()
        json_str = jsonlib.dumps(payload, ensure_ascii=False)
        now = datetime.utcnow()
        if row:
            row.data = json_str
            row.updated_at = now
        else:
            session.add(UserData(key=storage_key, data=json_str, updated_at=now))
        await session.commit()

    return {"status": "ok", "storage_key": storage_key, **payload}



# ─── 검수 페이지 JSON (NN-1) ──────────────────────


@router.get("/api/review/{target_date}")
async def get_review_payload(target_date: str):
    """검수용 풀 데이터 — auto-build snapshot + 큐텐 콘텐츠/매칭 사유/옵션 enrich.

    React /review/:date 페이지가 fetch.
    accepted 와 cheapest fallback 모두 반환 (프론트가 토글로 분리).
    """
    from app.db.models import (
        Qoo10Product, DomesticMatchCandidate, DomesticProductOption,
    )
    storage_key = f"last_auto_collected:{target_date}"
    async with async_session() as session:
        row = (await session.execute(
            select(UserData).where(UserData.key == storage_key)
        )).scalar_one_or_none()
    if not row:
        return {"date": target_date, "candidates": [], "error": "no_snapshot"}

    try:
        payload = jsonlib.loads(row.data)
    except Exception:
        return {"date": target_date, "candidates": [], "error": "snapshot_parse_failed"}

    candidates = payload.get("candidates") or []

    # enrich — 큐텐 콘텐츠 + 매칭 사유 + 옵션
    async with async_session() as s:
        for c in candidates:
            kw_jp = c.get("keyword_jp")
            ch = c.get("cheapest_domestic") or {}
            d_id = ch.get("id")

            # 1) 큐텐 콘텐츠 — search_keyword 의 첫 (콘텐츠 채워진) 큐텐 product
            if kw_jp:
                qres = (await s.execute(
                    select(
                        Qoo10Product.cover_image_url,
                        Qoo10Product.qoo10_title_jp,
                        Qoo10Product.qoo10_tags,
                        Qoo10Product.qoo10_marketing,
                        Qoo10Product.qoo10_option_name,
                        Qoo10Product.product_name,
                        Qoo10Product.product_name_ko,
                        Qoo10Product.qoo10_jp_detail,
                    )
                    .where(Qoo10Product.search_keyword == kw_jp)
                    .where(Qoo10Product.qoo10_title_jp.is_not(None))
                    .limit(1)
                )).first()
                # 콘텐츠 미생성 케이스 — 일반 큐텐 product 1개라도
                if not qres:
                    qres = (await s.execute(
                        select(
                            Qoo10Product.cover_image_url,
                            Qoo10Product.qoo10_title_jp,
                            Qoo10Product.qoo10_tags,
                            Qoo10Product.qoo10_marketing,
                            Qoo10Product.qoo10_option_name,
                            Qoo10Product.product_name,
                            Qoo10Product.product_name_ko,
                            Qoo10Product.qoo10_jp_detail,
                        )
                        .where(Qoo10Product.search_keyword == kw_jp)
                        .limit(1)
                    )).first()
                if qres:
                    cov, title, tags, marketing, opt, jp_name, ko_name, jp_detail_raw = qres
                    try:
                        tags_list = jsonlib.loads(tags) if tags else []
                    except Exception:
                        tags_list = []
                    try:
                        marketing_list = jsonlib.loads(marketing) if marketing else []
                    except Exception:
                        marketing_list = []
                    jp_detail = None
                    if jp_detail_raw:
                        try:
                            jp_detail = jsonlib.loads(jp_detail_raw)
                        except Exception:
                            jp_detail = None
                    c["qoo10"] = {
                        "cover_image_url": cov or "",
                        "product_name_jp": jp_name or "",
                        "product_name_ko": ko_name or "",
                        "title_jp": title or "",
                        "tags": tags_list,
                        "marketing_points": marketing_list,
                        "option_name": opt or "",
                        "jp_detail": jp_detail,  # FFFF-1
                    }

            # 2) 매칭 사유 — DomesticMatchCandidate
            if d_id:
                mres = (await s.execute(
                    select(
                        DomesticMatchCandidate.image_score,
                        DomesticMatchCandidate.name_score,
                        DomesticMatchCandidate.image_match_note,
                        DomesticMatchCandidate.decision,
                    )
                    .where(DomesticMatchCandidate.domestic_product_id == d_id)
                    .order_by(DomesticMatchCandidate.image_score.desc().nullslast())
                    .limit(1)
                )).first()
                if mres:
                    img_s, name_s, note, dec = mres
                    c["match"] = {
                        "image_score": float(img_s) if img_s is not None else None,
                        "name_score": float(name_s) if name_s is not None else None,
                        "note": (note or "")[:200],
                        "decision": dec or "pending",
                    }

            # 3) 옵션 풀세트 — DomesticProductOption
            if d_id:
                opts = (await s.execute(
                    select(
                        DomesticProductOption.option_name,
                        DomesticProductOption.option_price_krw,
                        DomesticProductOption.in_stock,
                    )
                    .where(DomesticProductOption.domestic_product_id == d_id)
                    .order_by(DomesticProductOption.option_price_krw.asc().nullslast())
                )).all()
                if opts:
                    c["options_full"] = [
                        {"name": n, "price_krw": p, "in_stock": bool(s_)} for n, p, s_ in opts
                    ]

    return {
        "date": target_date,
        "generated_at": payload.get("generated_at"),
        "min_margin_rate": payload.get("min_margin_rate"),
        "count": len(candidates),
        "candidates": candidates,
    }


# ─── 시트 row 메타 (TT-1C) ─────────────────────────


@router.get("/api/sheet/row-meta")
async def get_sheet_row_meta(keyword_jp: str = "", product_name: str = ""):
    """시트 row 우측 패널이 fetch — 큐텐 콘텐츠 + 매칭 사유 + 옵션 풀세트.

    keyword_jp 우선 매칭. 없으면 product_name 으로 한국 상품 → 매칭 candidate 역추적.
    """
    from app.db.models import (
        Qoo10Product, DomesticProduct, DomesticMatchCandidate, DomesticProductOption,
    )
    out: dict = {"qoo10": None, "match": None, "options_full": None}

    if not keyword_jp and not product_name:
        return out

    async with async_session() as s:
        # 1) 큐텐 콘텐츠 — keyword_jp 매칭 큐텐 product 1건
        if keyword_jp:
            qres = (await s.execute(
                select(
                    Qoo10Product.id,
                    Qoo10Product.cover_image_url,
                    Qoo10Product.qoo10_title_jp,
                    Qoo10Product.qoo10_tags,
                    Qoo10Product.qoo10_marketing,
                    Qoo10Product.qoo10_option_name,
                    Qoo10Product.product_name,
                    Qoo10Product.product_name_ko,
                    Qoo10Product.cover_description,
                )
                .where(Qoo10Product.search_keyword == keyword_jp)
                .where(Qoo10Product.qoo10_title_jp.is_not(None))
                .limit(1)
            )).first()
            if not qres:
                qres = (await s.execute(
                    select(
                        Qoo10Product.id,
                        Qoo10Product.cover_image_url,
                        Qoo10Product.qoo10_title_jp,
                        Qoo10Product.qoo10_tags,
                        Qoo10Product.qoo10_marketing,
                        Qoo10Product.qoo10_option_name,
                        Qoo10Product.product_name,
                        Qoo10Product.product_name_ko,
                        Qoo10Product.cover_description,
                    )
                    .where(Qoo10Product.search_keyword == keyword_jp)
                    .limit(1)
                )).first()
            if qres:
                qid, cov, title, tags, marketing, opt, jp_name, ko_name, cov_desc = qres
                try:
                    tags_list = jsonlib.loads(tags) if tags else []
                except Exception:
                    tags_list = []
                try:
                    marketing_list = jsonlib.loads(marketing) if marketing else []
                except Exception:
                    marketing_list = []
                out["qoo10"] = {
                    "id": qid,
                    "cover_image_url": cov or "",
                    "product_name_jp": jp_name or "",
                    "product_name_ko": ko_name or "",
                    "title_jp": title or "",
                    "tags": tags_list,
                    "marketing_points": marketing_list,
                    "option_name": opt or "",
                    "cover_description": cov_desc or "",
                }

        # 2) 한국 상품 ID — product_name 으로 (또는 이미 큐텐 매칭의 cheapest 사용)
        d_id = None
        if product_name:
            dres = (await s.execute(
                select(DomesticProduct.id)
                .where(DomesticProduct.product_name == product_name)
                .order_by(DomesticProduct.id.desc())
                .limit(1)
            )).first()
            if dres:
                d_id = dres[0]

        # 3a) 한국 cover description (GGG-1) + extras 평가 (VVV-1/WWW-1)
        if d_id:
            drow = (await s.execute(
                select(
                    DomesticProduct.cover_description,
                    DomesticProduct.extras_eval_json,
                ).where(DomesticProduct.id == d_id).limit(1)
            )).first()
            if drow:
                desc, extras_json = drow
                extras = []
                if extras_json:
                    try:
                        extras = jsonlib.loads(extras_json)
                        # score DESC 정렬 (None 은 마지막)
                        extras.sort(key=lambda x: -(x.get("score") if x.get("score") is not None else -1))
                    except Exception:
                        extras = []
                out["domestic"] = {
                    "id": d_id,
                    "cover_description": desc or "",
                    "extras": extras,
                }

        # 3) 매칭 사유 — domestic_id 기준 가장 높은 image_score
        if d_id:
            mres = (await s.execute(
                select(
                    DomesticMatchCandidate.image_score,
                    DomesticMatchCandidate.name_score,
                    DomesticMatchCandidate.image_match_note,
                    DomesticMatchCandidate.decision,
                    DomesticMatchCandidate.quality_score,
                )
                .where(DomesticMatchCandidate.domestic_product_id == d_id)
                .order_by(DomesticMatchCandidate.image_score.desc().nullslast())
                .limit(1)
            )).first()
            if mres:
                img_s, name_s, note, dec, q_s = mres
                out["match"] = {
                    "image_score": float(img_s) if img_s is not None else None,
                    "name_score": float(name_s) if name_s is not None else None,
                    "quality_score": float(q_s) if q_s is not None else None,
                    "note": (note or "")[:200],
                    "decision": dec or "pending",
                }

            # 4) 옵션 풀세트
            opts = (await s.execute(
                select(
                    DomesticProductOption.option_name,
                    DomesticProductOption.option_price_krw,
                    DomesticProductOption.in_stock,
                )
                .where(DomesticProductOption.domestic_product_id == d_id)
                .order_by(DomesticProductOption.option_price_krw.asc().nullslast())
            )).all()
            if opts:
                out["options_full"] = [
                    {"name": n, "price_krw": p, "in_stock": bool(s_)} for n, p, s_ in opts
                ]

        # 5) FFF-1 — alt 한국 SKU (cheapest 외, 사장님이 swap 가능)
        if keyword_jp:
            from app.db.models import Keyword as _K
            kw_kr_q = (await s.execute(
                select(_K.keyword_kr).where(_K.keyword_jp == keyword_jp).limit(1)
            )).first()
            kw_kr = (kw_kr_q[0] if kw_kr_q else None) or ""
            if kw_kr:
                alt_rows = (await s.execute(
                    select(
                        DomesticProduct.id, DomesticProduct.product_name,
                        DomesticProduct.price_krw, DomesticProduct.product_url,
                        DomesticProduct.cover_image_url, DomesticProduct.source,
                        DomesticProduct.image_score_overall,
                        DomesticProduct.cover_description,
                    )
                    .where(DomesticProduct.search_keyword == kw_kr)
                    .where(DomesticProduct.cover_image_url.is_not(None))
                    .where(DomesticProduct.price_krw > 0)
                    .order_by(DomesticProduct.price_krw.asc())
                    .limit(10)
                )).all()
                if alt_rows:
                    out["alt_skus"] = [
                        {
                            "id": aid, "source": asrc, "product_name": aname,
                            "price_krw": aprice, "product_url": aurl,
                            "cover_image_url": acov, "image_score": ascore,
                            "cover_description": adesc,
                            "is_current_cheapest": (aid == d_id),
                        }
                        for aid, aname, aprice, aurl, acov, asrc, ascore, adesc in alt_rows
                    ]

        # 6) 큐텐 원본 cover N개 (가격 ASC) — 사장님이 큐텐 vs 한국 비교
        if keyword_jp:
            qsamples = (await s.execute(
                select(
                    Qoo10Product.id, Qoo10Product.product_name,
                    Qoo10Product.product_name_ko, Qoo10Product.price_jpy,
                    Qoo10Product.cover_image_url, Qoo10Product.product_url,
                    Qoo10Product.cover_description,
                )
                .where(Qoo10Product.search_keyword == keyword_jp)
                .where(Qoo10Product.cover_image_url.is_not(None))
                .where(Qoo10Product.price_jpy > 0)
                .order_by(Qoo10Product.price_jpy.asc())
                .limit(8)
            )).all()
            if qsamples:
                out["qoo10_samples"] = [
                    {
                        "id": qid, "product_name": qname, "product_name_ko": qko,
                        "price_jpy": qprice, "product_url": qurl, "cover_image_url": qcov,
                        "cover_description": qdesc,
                    }
                    for qid, qname, qko, qprice, qcov, qurl, qdesc in qsamples
                ]

    return out


# ─── 사장님 수정 기록 (FFF-2) ─────────────────────────


class CorrectionRequest(BaseModel):
    keyword_jp: str = ""
    keyword_kr: str = ""
    decision_kind: str  # 'swap' | 'reject' | 'accept_as_is'
    ai_choice_id: Optional[int] = None
    ai_choice_name: str = ""
    ai_choice_url: str = ""
    ai_choice_cover_url: str = ""
    ai_image_score: Optional[float] = None
    ai_name_score: Optional[float] = None
    user_choice_id: Optional[int] = None
    user_choice_name: str = ""
    user_choice_url: str = ""
    user_choice_cover_url: str = ""
    user_note: str = ""


@router.post("/api/sheet/correction")
async def record_correction(req: CorrectionRequest):
    """사장님 수정 기록 (시트 swap/reject 시 frontend 가 호출).

    누적 데이터로 image_match prompt 개선/임계값 조정/fine-tune source.
    """
    from app.db.models import UserCorrection
    if req.decision_kind not in ("swap", "reject", "accept_as_is"):
        return {"error": "decision_kind: swap | reject | accept_as_is"}
    try:
        async with async_session() as session:
            session.add(UserCorrection(
                keyword_jp=req.keyword_jp or None,
                keyword_kr=req.keyword_kr or None,
                decision_kind=req.decision_kind,
                ai_choice_id=req.ai_choice_id,
                ai_choice_name=req.ai_choice_name or None,
                ai_choice_url=req.ai_choice_url or None,
                ai_choice_cover_url=req.ai_choice_cover_url or None,
                ai_image_score=req.ai_image_score,
                ai_name_score=req.ai_name_score,
                user_choice_id=req.user_choice_id,
                user_choice_name=req.user_choice_name or None,
                user_choice_url=req.user_choice_url or None,
                user_choice_cover_url=req.user_choice_cover_url or None,
                user_note=req.user_note or None,
            ))
            await session.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@router.get("/api/sheet/corrections/metrics")
async def correction_metrics():
    """학습 루프 metrics — AI vs 사장님 swap/reject 누적 통계 (학습 효과 추적).

    - total: 누적 corrections 수
    - by_kind: swap/reject/accept_as_is 분포
    - ai_avg_image_score: AI 가 매겼던 image_score 평균 (낮을수록 모델 신뢰도 ↓)
    - swap_count_recent_7d: 최근 7일 swap 수
    - top_keywords: 가장 많이 swap 된 키워드 top 5
    """
    from datetime import timedelta
    from app.db.models import UserCorrection
    async with async_session() as s:
        rows = (await s.execute(
            select(UserCorrection)
        )).scalars().all()

    if not rows:
        return {"total": 0, "message": "corrections 0건 — 사장님 swap/reject 누적 후 의미 있는 통계"}

    by_kind: dict[str, int] = {}
    img_scores = []
    kw_swap: dict[str, int] = {}
    cutoff_7d = datetime.utcnow() - timedelta(days=7)
    swap_recent = 0

    for r in rows:
        k = r.decision_kind or "unknown"
        by_kind[k] = by_kind.get(k, 0) + 1
        if r.ai_image_score is not None:
            img_scores.append(float(r.ai_image_score))
        if k == "swap" and r.keyword_jp:
            kw_swap[r.keyword_jp] = kw_swap.get(r.keyword_jp, 0) + 1
        if k == "swap" and r.corrected_at and r.corrected_at >= cutoff_7d:
            swap_recent += 1

    top_keywords = sorted(kw_swap.items(), key=lambda x: -x[1])[:5]
    avg_img = sum(img_scores) / len(img_scores) if img_scores else None

    # AI 정확도 추정 (rough): 1 - swap_rate.
    # swap → AI 가 잘못 매칭, accept_as_is → AI 가 잘 매칭
    swap_n = by_kind.get("swap", 0)
    accept_n = by_kind.get("accept_as_is", 0)
    rate_basis = swap_n + accept_n
    ai_accuracy = (accept_n / rate_basis) if rate_basis > 0 else None

    return {
        "total": len(rows),
        "by_kind": by_kind,
        "ai_avg_image_score": round(avg_img, 3) if avg_img is not None else None,
        "ai_accuracy_estimate": round(ai_accuracy, 3) if ai_accuracy is not None else None,
        "swap_count_recent_7d": swap_recent,
        "top_swapped_keywords": [{"keyword_jp": k, "count": c} for k, c in top_keywords],
        "tip": (
            "swap 가 많은 키워드는 image_match prompt 또는 임계값 조정 후보. "
            "ai_avg_image_score 가 낮으면 vision 모델 교체 검토."
        ),
    }


@router.get("/api/sheet/corrections")
async def list_corrections(limit: int = 100):
    """사장님 수정 사례 list — RD 진단/분석용."""
    from app.db.models import UserCorrection
    async with async_session() as session:
        rows = (await session.execute(
            select(UserCorrection).order_by(desc(UserCorrection.corrected_at)).limit(limit)
        )).scalars().all()
    return {
        "count": len(rows),
        "corrections": [
            {
                "id": r.id, "keyword_jp": r.keyword_jp, "keyword_kr": r.keyword_kr,
                "decision_kind": r.decision_kind,
                "ai_choice_id": r.ai_choice_id, "ai_choice_name": r.ai_choice_name,
                "ai_image_score": r.ai_image_score,
                "user_choice_id": r.user_choice_id, "user_choice_name": r.user_choice_name,
                "corrected_at": r.corrected_at.isoformat() if r.corrected_at else None,
            }
            for r in rows
        ],
    }


# ─── 시트로 보내기 ─────────────────────────────────

class SheetItemInput(BaseModel):
    """HTML 결과 페이지에서 사용자가 직접 편집한 시트 행 입력값."""
    keyword_jp: str
    # 시트 셀에서 편집 가능한 필드들 (상품시트와 동일 양식)
    product_name: str = ""
    product_name_ko: str = ""
    product_url: str = ""
    cover_image_url: str = ""
    weight_g: float = 0
    item_price_krw: int = 0
    domestic_shipping_krw: int = 0
    shipping_packaging_krw: int = 3000
    sell_price_jpy: int = 0
    exchange_rate: float = 9.5
    shipping_mode: str = "auto"


class SendToSheetRequest(BaseModel):
    items: list[SheetItemInput] = Field(default_factory=list)
    # 하위 호환 — 키워드만 보내는 옛 형식
    keywords_jp: list[str] = Field(default_factory=list)


@router.post("/api/recommend/send-to-sheet/{target_date}")
async def send_to_sheet(target_date: str, req: SendToSheetRequest):
    """자동화 후보 중 선택된 키워드를 product_sheet 에 머지.

    프론트엔드의 cloudSync 가 페이지 진입 시 user_data 를 fetch 하므로
    이 엔드포인트가 user_data 의 product_sheet 키만 업데이트하면
    프론트는 다음 새로고침 때 자동 반영된다 (코드 변경 없음).

    items[].weight_g, items[].price_krw 는 사용자가 HTML 결과 페이지에서
    직접 보정한 값. 0 이면 자동화 결과 그대로 사용.
    """
    # items 우선, 없으면 keywords_jp 폴백
    items_input: list[SheetItemInput] = list(req.items)
    if not items_input and req.keywords_jp:
        items_input = [SheetItemInput(keyword_jp=k) for k in req.keywords_jp]

    if not items_input:
        return {"added": 0, "skipped": 0, "message": "선택된 키워드 없음"}

    # 1. 자동화 결과 읽기
    auto_key = f"last_auto_collected:{target_date}"
    async with async_session() as session:
        r = await session.execute(select(UserData).where(UserData.key == auto_key))
        auto_row = r.scalar_one_or_none()
    if not auto_row:
        return {"error": f"자동화 결과 없음: {target_date}"}
    try:
        auto_data = jsonlib.loads(auto_row.data)
    except Exception:
        return {"error": "자동화 결과 JSON 파싱 실패"}

    candidates = auto_data.get("candidates") or []
    # keyword_jp → 사용자 입력값 매핑
    user_input_map: dict[str, SheetItemInput] = {it.keyword_jp: it for it in items_input}
    selected = [c for c in candidates if c.get("keyword_jp") in user_input_map]
    if not selected:
        return {"added": 0, "skipped": 0, "message": "후보에 매칭되는 키워드 없음"}

    # R-7: 카테고리 lookup — keyword_jp → category_inferred (LLM 6분류)
    selected_kws = [c.get("keyword_jp") for c in selected if c.get("keyword_jp")]
    cat_map: dict[str, str] = {}
    if selected_kws:
        async with async_session() as session:
            from app.db.models import Keyword as _K
            res = await session.execute(
                select(_K.keyword_jp, _K.category_inferred, _K.category)
                .where(_K.keyword_jp.in_(selected_kws))
            )
            for row in res.all():
                jp = row[0]
                if jp and jp not in cat_map:
                    cat_map[jp] = (row[1] or row[2] or "")

    # 2. 기존 시트 읽기
    async with async_session() as session:
        r = await session.execute(
            select(UserData).where(UserData.key == "product_sheet")
        )
        sheet_row_obj = r.scalar_one_or_none()

    existing_rows: list[dict] = []
    if sheet_row_obj:
        try:
            parsed = jsonlib.loads(sheet_row_obj.data)
            if isinstance(parsed, list):
                existing_rows = parsed
        except Exception:
            existing_rows = []

    # 중복 체크 — product_name 또는 notes 의 keyword_jp 기준
    existing_names = {r.get("product_name", "") for r in existing_rows if r.get("product_name")}
    existing_keywords = set()
    incoming_kws = list(user_input_map.keys())
    for r in existing_rows:
        notes = r.get("notes") or ""
        for kw in incoming_kws:
            if kw and kw in notes:
                existing_keywords.add(kw)

    # 3. 자동화 candidate → SheetRow 변환
    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    new_rows: list[dict] = []
    skipped = 0

    for c in selected:
        kw_jp = c.get("keyword_jp", "")
        ch = c.get("cheapest_domestic") or {}
        user_input = user_input_map.get(kw_jp)

        # 모든 필드 사용자 편집값 우선, 없으면 candidate 값
        def _u(field: str, fallback):
            if user_input is None:
                return fallback
            v = getattr(user_input, field, None)
            if isinstance(v, str):
                v = v.strip()
            return v if (v not in (None, "", 0)) else fallback

        product_name = _u("product_name", "") or (
            (ch.get("product_name") or "").strip()
            or (c.get("keyword_kr") or "").strip()
            or kw_jp
        )
        if not product_name:
            skipped += 1
            continue

        # 중복: product_name 같거나 같은 keyword_jp 가 이미 시트에 있으면 스킵
        if product_name in existing_names or kw_jp in existing_keywords:
            skipped += 1
            continue

        # K (5/3) 블랙리스트 사전 차단 — keyword_jp 또는 product_name 매칭 시 시트 추가 안 함
        from app.api.blacklist import is_blacklisted as _is_blk
        if await _is_blk(keyword_jp=kw_jp, product_name=product_name):
            skipped += 1
            continue

        margin = c.get("margin") or {}
        margin_rate_pct = (margin.get("margin_rate") or 0) * 100

        notes_parts = [f"[자동:{target_date}] keyword_jp={kw_jp}"]
        notes_parts.append(f"추정 마진율 {margin_rate_pct:.1f}%")
        weight_val = float(_u("weight_g", 0))
        if weight_val <= 0:
            notes_parts.append("⚠️ 무게 미입력")

        new_rows.append({
            "id": str(uuid.uuid4()),
            "product_name": product_name,
            "category": cat_map.get(kw_jp, ""),  # R-7 시트 카테고리 컬럼 자동 채움
            "product_name_ko": _u("product_name_ko", "") or (c.get("keyword_kr") or ""),
            "product_url": _u("product_url", "") or (ch.get("product_url") or ""),
            "cover_image_url": _u("cover_image_url", "") or (ch.get("cover_image_url") or ""),
            "source": f"auto:{target_date}",
            "shop_rank": None,
            "review_count": None,
            "created_at": today_iso,
            "weight_g": weight_val,
            "item_price_krw": int(_u("item_price_krw", 0) or ch.get("price_krw") or 0),
            "domestic_shipping_krw": int(_u("domestic_shipping_krw", 0) or 0),
            "shipping_packaging_krw": int(_u("shipping_packaging_krw", 3000) or 3000),
            "competitor_price_jpy": int(c.get("qoo10_avg_jpy") or 0),
            "sell_price_jpy": int(_u("sell_price_jpy", 0) or c.get("qoo10_avg_jpy") or 0),
            "normal_sales_count": 0,
            "mega_sales_count": 0,
            "exchange_rate": float(_u("exchange_rate", 9.5) or 9.5),
            "shipping_mode": _u("shipping_mode", "auto") or "auto",
            "compositions": [],
            "notes": " — ".join(notes_parts),
        })
        existing_names.add(product_name)
        existing_keywords.add(kw_jp)

    # 4. 머지 후 저장 (덮어쓰기 X — append 방식)
    merged = existing_rows + new_rows
    payload_str = jsonlib.dumps(merged, ensure_ascii=False)
    now = datetime.utcnow()

    async with async_session() as session:
        r = await session.execute(
            select(UserData).where(UserData.key == "product_sheet")
        )
        target = r.scalar_one_or_none()
        if target:
            target.data = payload_str
            target.updated_at = now
        else:
            session.add(UserData(key="product_sheet", data=payload_str, updated_at=now))
        await session.commit()

    return {
        "added": len(new_rows),
        "skipped": skipped,
        "total_in_sheet": len(merged),
        "message": (
            f"{len(new_rows)}개 추가, {skipped}개 스킵 — 총 시트 {len(merged)}행. "
            f"/recommend-products 페이지 새로고침하면 반영됨."
        ),
    }


# ─── R-7 시트 카테고리 백필 ───────────────────────────────


@router.post("/api/sheet/backfill-categories")
async def backfill_sheet_categories():
    """기존 product_sheet 행 중 category 비어있는 것 → keyword_jp 매핑으로 LLM 분류 가져와 채움.

    1) UserData product_sheet 로드
    2) category 비어있고 keyword_jp 있는 행만 추출
    3) keyword DB 에서 category_inferred (LLM 6분류) 또는 category (raw) lookup
    4) 시트 update + 저장
    5) 결과 반환
    """
    from app.db.models import Keyword as _K

    async with async_session() as session:
        r = await session.execute(
            select(UserData).where(UserData.key == "product_sheet")
        )
        row = r.scalar_one_or_none()
    if not row:
        return {"error": "product_sheet 없음"}

    try:
        sheet = jsonlib.loads(row.data)
    except Exception:
        return {"error": "product_sheet JSON 파싱 실패"}
    if not isinstance(sheet, list):
        return {"error": "product_sheet 형식 오류 (list 아님)"}

    # 비어있는 행만
    targets = [r for r in sheet if isinstance(r, dict) and not (r.get("category") or "").strip() and (r.get("keyword_jp") or "").strip()]
    if not targets:
        return {"updated": 0, "skipped": len(sheet), "message": "백필할 행 없음 (모두 카테고리 채워짐)"}

    kws = list({t.get("keyword_jp") for t in targets if t.get("keyword_jp")})
    cat_map: dict[str, str] = {}
    async with async_session() as session:
        res = await session.execute(
            select(_K.keyword_jp, _K.category_inferred, _K.category)
            .where(_K.keyword_jp.in_(kws))
        )
        for kw_jp, c_inf, c_raw in res.all():
            if kw_jp and kw_jp not in cat_map:
                v = (c_inf or c_raw or "").strip()
                if v:
                    cat_map[kw_jp] = v

    updated = 0
    for r in targets:
        kw = r.get("keyword_jp")
        cat = cat_map.get(kw)
        if cat:
            r["category"] = cat
            updated += 1

    if updated == 0:
        return {
            "updated": 0,
            "skipped": len(sheet),
            "candidates": len(targets),
            "matched_in_db": len(cat_map),
            "message": f"{len(targets)}개 행에 keyword_jp 가 있지만 keywords DB 매칭 카테고리 0개",
        }

    # 저장
    payload_str = jsonlib.dumps(sheet, ensure_ascii=False)
    now = datetime.utcnow()
    async with async_session() as session:
        r = await session.execute(
            select(UserData).where(UserData.key == "product_sheet")
        )
        target = r.scalar_one_or_none()
        if target:
            target.data = payload_str
            target.updated_at = now
            await session.commit()

    return {
        "updated": updated,
        "skipped": len(sheet) - updated,
        "candidates": len(targets),
        "matched_in_db": len(cat_map),
        "message": f"{updated}개 행 카테고리 백필 완료. /recommend-products 새로고침하면 반영됨.",
    }


# ─── U. 샵 벤치마크 자동 동기화 (5/3) ───────────────────────────


class ShopBenchSyncRequest(BaseModel):
    shop_urls: list[str] = Field(default_factory=list)  # 비어있으면 UserData "shop_urls" 사용
    limit_per_shop: int = 50
    sort_type: str = "review"


@router.post("/api/automation/shop-benchmark-sync")
async def shop_benchmark_sync(req: ShopBenchSyncRequest):
    """야간 자동화 — 등록된 샵들에서 fetch + 신규 상품 표시.

    last_seen_set (UserData "shop_last_seen:{shop_id}") 와 비교해 is_new 플래그.
    결과는 shop_cache (UserData) 에 저장 — ShopBenchmarkPage 가 자동 로드.
    """
    from app.scrapers.m13_shop_products import Qoo10ShopScraper
    from app.browser.manager import browser_manager
    from app.services.task_manager import task_manager as _tm

    # 1) 샵 URL 목록 결정
    urls = list(req.shop_urls)
    if not urls:
        async with async_session() as s:
            r = await s.execute(select(UserData).where(UserData.key == "shop_urls"))
            row = r.scalar_one_or_none()
        if row:
            try:
                arr = jsonlib.loads(row.data)
                if isinstance(arr, list):
                    urls = [e.get("url") for e in arr if isinstance(e, dict) and e.get("url")]
            except Exception:
                urls = []
    if not urls:
        return {"error": "샵 URL 없음 — ShopBenchmarkPage 에서 추가하세요"}

    # 2) 브라우저 준비
    try:
        await browser_manager.get_page()
    except Exception as e:
        return {"error": f"browser_manager 준비 실패: {e}"}

    # 3) 각 샵 scraper 호출 + last_seen 비교
    summary = []
    cache_results: list[dict] = []

    async def _load_last_seen(shop_id: str) -> set[str]:
        async with async_session() as s:
            r = await s.execute(select(UserData).where(UserData.key == f"shop_last_seen:{shop_id}"))
            row = r.scalar_one_or_none()
        if not row:
            return set()
        try:
            arr = jsonlib.loads(row.data)
            return set(arr) if isinstance(arr, list) else set()
        except Exception:
            return set()

    async def _save_last_seen(shop_id: str, urls_set: set[str]):
        payload = jsonlib.dumps(sorted(urls_set), ensure_ascii=False)
        now = datetime.utcnow()
        async with async_session() as s:
            r = await s.execute(select(UserData).where(UserData.key == f"shop_last_seen:{shop_id}"))
            row = r.scalar_one_or_none()
            if row:
                row.data = payload
                row.updated_at = now
            else:
                s.add(UserData(key=f"shop_last_seen:{shop_id}", data=payload, updated_at=now))
            await s.commit()

    for shop_url in urls:
        try:
            scraper = Qoo10ShopScraper(browser_manager, _tm)
            res = await scraper.run(
                shop_url=shop_url,
                limit=req.limit_per_shop,
                sort_type=req.sort_type,
            )
            shop_id = res.get("shop_id") or shop_url.rstrip("/").rsplit("/", 1)[-1]
            products = res.get("products") or []
            for p in products:
                ld = p.get("lookup_date")
                if ld is not None and not isinstance(ld, str):
                    p["lookup_date"] = str(ld)

            # last_seen 비교 → is_new 플래그
            last_seen = await _load_last_seen(shop_id)
            new_count = 0
            current_set: set[str] = set()
            for p in products:
                u = p.get("product_url") or ""
                if u:
                    current_set.add(u)
                    p["is_new"] = u not in last_seen
                    if p["is_new"]:
                        new_count += 1

            # last_seen 갱신 — 첫 fetch 라면 모두 NEW 표시 후 baseline
            await _save_last_seen(shop_id, current_set)

            cache_results.append({
                "shop_id": shop_id,
                "shop_url": res.get("shop_url") or shop_url,
                "products": products,
                "shop_meta": res.get("shop_meta") or {},
                "fetched_at": datetime.utcnow().isoformat(),
                "sort_type": req.sort_type,
            })
            summary.append({
                "shop_id": shop_id,
                "total": len(products),
                "new": new_count,
                "first_run": len(last_seen) == 0,
            })
        except Exception as e:
            logger.warning(f"[shop_sync] {shop_url} 실패: {e}")
            summary.append({"shop_id": shop_url, "error": str(e)[:200]})

    # 4) shop_cache UserData 갱신 (프론트가 자동 로드)
    payload = jsonlib.dumps(cache_results, ensure_ascii=False)
    now = datetime.utcnow()
    async with async_session() as s:
        r = await s.execute(select(UserData).where(UserData.key == "shop_cache"))
        row = r.scalar_one_or_none()
        if row:
            row.data = payload
            row.updated_at = now
        else:
            s.add(UserData(key="shop_cache", data=payload, updated_at=now))
        await s.commit()

    total_new = sum(s.get("new", 0) for s in summary)
    return {
        "shops": len(urls),
        "total_new": total_new,
        "summary": summary,
    }


# ─── C. 야간 URL 일괄 재생성 (시트의 미수집 URL 자동 처리) ──────


class UrlBatchRegenerateRequest(BaseModel):
    limit: int = 30                       # 한 번에 처리할 최대 행 수
    include_jp_detail: bool = False       # JP 상세 카피도 생성?
    skip_if_filled: bool = True           # 이미 채워진 행 스킵
    row_ids: Optional[list[str]] = None   # N (5/3) — 지정 시 그 ID 행만 처리 (사장님 선택 multi-select)


@router.post("/api/automation/url-batch-regenerate")
async def url_batch_regenerate(req: UrlBatchRegenerateRequest):
    """야간 자동화용 — 시트의 URL 있고 데이터 미수집 행을 자동 fetch+SEO 처리.

    URL 도메인별 라우팅 (_do_regenerate 안에서 분기):
      - Naver smartstore/brand: 크롬 확장 (메인 Chrome 켜져있어야)
      - Coupang: 백엔드 Scrapling (Chrome 무관, PC 만 켜져있으면 됨)

    background task — 즉시 task_id 반환, /api/tasks/{task_id} 폴링.
    각 행 처리 후 시트 부분 저장 (오류 시 진행분 보존).
    """
    import asyncio as _asyncio
    from app.api.products import _do_regenerate
    from app.services.task_manager import task_manager

    # 1) 시트 로드
    async with async_session() as session:
        r = await session.execute(select(UserData).where(UserData.key == "product_sheet"))
        row = r.scalar_one_or_none()
    if not row:
        return {"error": "product_sheet 없음"}
    try:
        sheet = jsonlib.loads(row.data)
    except Exception:
        return {"error": "product_sheet JSON 파싱 실패"}
    if not isinstance(sheet, list):
        return {"error": "product_sheet 형식 오류 (list 아님)"}

    # 2) 대상 필터
    # N (5/3): row_ids 지정 시 그 행만 처리 (skip_if_filled 무시 — 사장님 명시 선택)
    selected_id_set: set | None = None
    if req.row_ids:
        selected_id_set = {str(rid) for rid in req.row_ids if rid}

    def _in_backoff(r: dict) -> bool:
        """실패 backoff 체크 — 최근 실패 후 min(2^fail_count, 7) 일 내면 skip.

        탬버린즈 무한 반복 (5/12·5/13 0/30) 같은 영구 실패 URL 격리.
        사장님 수동 개입 없이 자동 회복 (성공 시 두 필드 모두 제거됨).
        선택 모드(row_ids 명시)는 사장님 의도이므로 backoff 무시.
        """
        if selected_id_set is not None:
            return False
        fail_count = int(r.get("_url_batch_fail_count") or 0)
        if fail_count <= 0:
            return False
        last_at = r.get("_url_batch_error_at")
        if not last_at:
            return False
        try:
            last_dt = datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
            if last_dt.tzinfo is not None:
                last_dt = last_dt.replace(tzinfo=None)
        except Exception:
            return False
        backoff_days = min(2 ** (fail_count - 1), 7)  # 1, 2, 4, 7, 7, ...
        elapsed = (datetime.utcnow() - last_dt).total_seconds() / 86400.0
        return elapsed < backoff_days

    def _needs_regen(r: dict) -> bool:
        if not isinstance(r, dict):
            return False
        url = (r.get("product_url") or "").strip().lower()
        qurl = (r.get("qoo10_url") or "").strip().lower()
        has_kr = bool(url) and ("naver.com" in url or "coupang.com" in url)
        has_qoo = "qoo10.jp" in qurl
        # 선택 모드 — ID 매칭 + 둘 중 하나라도 있어야 함
        if selected_id_set is not None:
            if str(r.get("id") or "") not in selected_id_set:
                return False
            return has_kr or has_qoo
        # 기본 모드 — 둘 중 하나라도 있고, 미수집이면 처리
        if not (has_kr or has_qoo):
            return False
        # 실패 backoff — 최근 실패한 행은 일정 기간 skip (탬버린즈 30건 무한 반복 방지)
        if _in_backoff(r):
            return False
        if not req.skip_if_filled:
            return True
        title_filled = bool((r.get("qoo10_title_jp") or "").strip())
        cover_filled = bool((r.get("cover_image_url") or "").strip())
        price_filled = (r.get("item_price_krw") or 0) > 0
        return not (title_filled and cover_filled and price_filled)

    # 선택 모드는 limit 무시 (사장님이 의도적으로 N개 골랐으면 그대로 처리)
    if selected_id_set is not None:
        targets = [r for r in sheet if _needs_regen(r)]
    else:
        targets = [r for r in sheet if _needs_regen(r)][: max(1, req.limit)]
    total = len(targets)
    if total == 0:
        return {"task_id": None, "total": 0, "message": "처리할 행 없음 (모두 채워져 있거나 URL 없음)"}

    task_id = task_manager.create_task(
        name=f"URL 일괄 재생성 ({total}건)", total=total,
    )

    async def _run():
        task_manager.start_task(task_id)
        success = 0
        failed = 0
        for idx, target_row in enumerate(targets, 1):
            # 사용자 중단 체크 — DELETE /api/tasks/{task_id} 시 fail_task 로 status='failed'
            t_check = task_manager.get_task(task_id)
            if t_check and t_check.status in ("failed", "cancelled"):
                logger.info(f"[url_batch] task {task_id} 사용자 중단 — {idx-1}건 처리 후 종료")
                return
            url = (target_row.get("product_url") or "").strip()
            name_hint = (target_row.get("product_name") or "").strip() or None
            cat_hint = (target_row.get("category") or "").strip() or None
            qoo10_url_hint = (target_row.get("qoo10_url") or "").strip() or None  # R (5/3)
            try:
                task_manager.update_progress(
                    task_id, increment=0,
                    message=f"[{idx}/{total}] {(name_hint or url)[:50]}",
                )
                result = await _do_regenerate(
                    url, req.include_jp_detail,
                    product_name_hint=name_hint,
                    category_hint=cat_hint,
                    qoo10_url_hint=qoo10_url_hint,
                )
                if result.get("error"):
                    failed += 1
                    target_row["_url_batch_error"] = result["error"][:200]
                    target_row["_url_batch_error_at"] = datetime.utcnow().isoformat()
                    target_row["_url_batch_fail_count"] = int(target_row.get("_url_batch_fail_count") or 0) + 1
                else:
                    def _merge(field: str, value):
                        """SEO/이미지/카피 등 LLM·페이지 추출 결과 — 항상 갱신 (사장님이 [컨텐츠 제작] 누른 의도)"""
                        if value not in (None, "", 0, []):
                            target_row[field] = value
                    def _merge_keep(field: str, value):
                        """사장님 수기 입력 보호 — 기존이 truthy 면 안 덮음. 빈 행만 자동 채움."""
                        if value in (None, "", 0, []):
                            return
                        cur = target_row.get(field)
                        if cur not in (None, "", 0, []):
                            return
                        target_row[field] = value
                    # 사장님 수기 입력 보호 — 가격/배송/SKU명/카테고리
                    _merge_keep("product_name", result.get("product_name"))
                    _merge_keep("item_price_krw", result.get("item_price_krw"))
                    _merge_keep("domestic_shipping_krw", result.get("domestic_shipping_krw"))
                    _merge_keep("category", result.get("category"))
                    # SEO/이미지/카피 — 항상 갱신
                    _merge("cover_image_url", result.get("cover_image_url"))
                    _merge("qoo10_title_jp", result.get("qoo10_title_jp"))
                    _merge("qoo10_tags", result.get("qoo10_tags"))
                    _merge("qoo10_marketing", result.get("qoo10_marketing"))
                    _merge("qoo10_marketing_ko", result.get("qoo10_marketing_ko"))
                    _merge("qoo10_option_name", result.get("qoo10_option_name"))
                    if result.get("qoo10_jp_detail"):
                        target_row["qoo10_jp_detail"] = result["qoo10_jp_detail"]
                    # 큐텐 경쟁가/배송 — 사장님 수기 입력 있으면 보호 (0 은 미입력으로 간주)
                    if result.get("competitor_price_jpy") is not None and not target_row.get("competitor_price_jpy"):
                        target_row["competitor_price_jpy"] = result["competitor_price_jpy"]
                    if result.get("competitor_shipping_jpy") is not None and not target_row.get("competitor_shipping_jpy"):
                        target_row["competitor_shipping_jpy"] = result["competitor_shipping_jpy"]
                    _merge("qoo10_cover_image_url", result.get("qoo10_cover_image_url"))
                    # raw 옵션 — 항상 갱신 (사장님 수기 편집 대상 X, 비교용)
                    if result.get("domestic_options") is not None:
                        target_row["domestic_options"] = result["domestic_options"]
                    if result.get("qoo10_options_raw") is not None:
                        target_row["qoo10_options_raw"] = result["qoo10_options_raw"]
                    _merge("cover_local_path", result.get("cover_local_path"))
                    _merge("detail_local_paths", result.get("detail_local_paths"))
                    _merge("image_folder", result.get("image_folder"))
                    target_row.pop("_url_batch_error", None)
                    target_row.pop("_url_batch_error_at", None)
                    target_row.pop("_url_batch_fail_count", None)
                    success += 1
            except Exception as e:
                failed += 1
                target_row["_url_batch_error"] = f"{type(e).__name__}: {e}"
                target_row["_url_batch_error_at"] = datetime.utcnow().isoformat()
                target_row["_url_batch_fail_count"] = int(target_row.get("_url_batch_fail_count") or 0) + 1
                logger.warning(f"[url_batch] {url[:60]} 실패: {e}")

            task_manager.update_progress(
                task_id, increment=1,
                message=f"[{idx}/{total}] 누적 성공 {success} / 실패 {failed}",
            )

            # 부분 저장 (각 행 후) — 오류 시 진행분 보존
            try:
                payload_str = jsonlib.dumps(sheet, ensure_ascii=False)
                now = datetime.utcnow()
                async with async_session() as session:
                    rr = await session.execute(
                        select(UserData).where(UserData.key == "product_sheet")
                    )
                    target = rr.scalar_one_or_none()
                    if target:
                        target.data = payload_str
                        target.updated_at = now
                        await session.commit()
            except Exception as e:
                logger.warning(f"[url_batch] 시트 저장 실패: {e}")

        task_manager.complete_task(
            task_id,
            message=f"URL 일괄 재생성 완료: 성공 {success} / 실패 {failed} / 전체 {total}",
        )

    _asyncio.create_task(_run())
    return {"task_id": task_id, "total": total, "status": "running"}
