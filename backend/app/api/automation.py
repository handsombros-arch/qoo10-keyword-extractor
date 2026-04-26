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
import math
import uuid
from datetime import date as date_cls, datetime
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
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
    brand_filter: str = Field("general", pattern="^(all|general|brand)$")
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
            "search_volume": sv,
            "kr_ratio": kr_ratio,
            "competition_intensity": comp,
        }

    filtered = []
    for kw in by_jp.values():
        if kw["search_volume"] < req.search_volume_min:
            continue
        if kw["kr_ratio"] < req.kr_ratio_min:
            continue
        if kw["competition_intensity"] <= 0:
            # 경쟁강도 미측정 키워드는 신뢰 불가 → 제외
            continue
        if kw["competition_intensity"] > req.competition_max:
            continue

        brand = _is_brand_keyword(kw["keyword_jp"])
        if req.brand_filter == "general" and brand:
            continue
        if req.brand_filter == "brand" and not brand:
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

            # 2) 큐텐 상품 통계 (판매가 후보)
            q = await session.execute(
                select(
                    func.count(Qoo10Product.id),
                    func.min(Qoo10Product.price_jpy),
                    func.avg(Qoo10Product.price_jpy),
                    func.max(Qoo10Product.price_jpy),
                ).where(
                    Qoo10Product.search_keyword == jp,
                    Qoo10Product.price_jpy > 0,
                )
            )
            qoo10_count, qoo10_min, qoo10_avg, qoo10_max = q.one()
            qoo10_count = qoo10_count or 0

            # 3) 국내 최저가 (구매가 후보)
            kw_ko = meta.get("keyword_kr") or ""
            cheapest = None
            if kw_ko:
                d = await session.execute(
                    select(DomesticProduct)
                    .where(
                        DomesticProduct.search_keyword == kw_ko,
                        DomesticProduct.price_krw > 0,
                    )
                    .order_by(DomesticProduct.price_krw.asc())
                    .limit(1)
                )
                row = d.scalar_one_or_none()
                if row:
                    cheapest = {
                        "source": row.source,
                        "product_name": row.product_name,
                        "price_krw": row.price_krw,
                        "product_url": row.product_url,
                        "cover_image_url": row.cover_image_url,
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


# ─── HTML 뷰 (브라우저로 결과 보기) ─────────────────

_BASE_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       padding: 1.5rem; background: #f5f5f5; color: #1f2937; }
h1, h2 { margin-top: 0; }
.card { background: white; padding: 1.25rem 1.5rem; border-radius: 8px;
        margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
table { background: white; border-collapse: collapse; width: 100%;
        border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
th, td { padding: 8px 12px; border-bottom: 1px solid #eef0f3; font-size: 13px; }
th { background: #f3f4f6; text-align: left; font-weight: 600; }
tr:hover { background: #f9fafb; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
.back { display: inline-block; margin-bottom: 1rem; }
.muted { color: #6b7280; font-size: 12px; }
.right { text-align: right; }
.tag { display: inline-block; padding: 2px 6px; border-radius: 4px;
       font-size: 11px; font-weight: 600; }
.tag-good { background: #d1fae5; color: #065f46; }
.tag-ok   { background: #fef3c7; color: #92400e; }
.tag-bad  { background: #fee2e2; color: #991b1b; }
"""


def _verdict_tag(verdict: str) -> str:
    cls = {
        "우수": "tag-good", "양호": "tag-good",
        "애매": "tag-ok", "부족": "tag-bad", "손실": "tag-bad",
    }.get(verdict, "")
    return f'<span class="tag {cls}">{verdict}</span>' if verdict else ""


@router.get("/api/recommend/auto-collected", response_class=HTMLResponse)
async def list_auto_collected_html():
    """저장된 야간 자동화 결과 날짜 목록 (HTML)."""
    async with async_session() as session:
        result = await session.execute(
            select(UserData.key, UserData.updated_at)
            .where(UserData.key.like("last_auto_collected:%"))
            .order_by(desc(UserData.updated_at))
        )
        rows = result.all()

    items_html = []
    for k, ua in rows:
        d = k.replace("last_auto_collected:", "")
        ts = ua.strftime("%Y-%m-%d %H:%M:%S") if ua else "-"
        items_html.append(
            f'<tr><td><a href="/api/recommend/auto-collected/{d}">{d}</a></td>'
            f'<td class="muted">{ts}</td></tr>'
        )
    body = "".join(items_html) or '<tr><td colspan="2" class="muted">저장된 결과 없음</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>야간 자동화 결과 목록</title>
<style>{_BASE_CSS}</style></head>
<body>
<div class="card">
  <h1>야간 자동화 결과 목록</h1>
  <p class="muted">날짜 클릭하면 해당 날짜의 추천 후보 표를 봅니다.</p>
</div>
<table>
  <thead><tr><th>날짜</th><th>마지막 업데이트</th></tr></thead>
  <tbody>{body}</tbody>
</table>
</body></html>"""


def _load_kse_table_json() -> str:
    """KSE 배송비 테이블을 JS 인라인용 JSON 문자열로 반환."""
    try:
        from app.config import settings
        path = settings.BASE_DIR / "app" / "data" / "qoo10_shipping_rates.json"
        data = jsonlib.loads(path.read_text(encoding="utf-8"))
        return jsonlib.dumps(data.get("free_kse", []), ensure_ascii=False)
    except Exception:
        return "[]"


@router.get("/api/recommend/auto-collected/{target_date}", response_class=HTMLResponse)
async def get_auto_collected_html(target_date: str):
    """특정 날짜의 자동화 결과 — 상품시트와 동일 양식의 편집 가능한 표."""
    storage_key = f"last_auto_collected:{target_date}"
    async with async_session() as session:
        result = await session.execute(
            select(UserData).where(UserData.key == storage_key)
        )
        row = result.scalar_one_or_none()

    if not row:
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>{_BASE_CSS}</style></head>
<body>
<a href="/api/recommend/auto-collected" class="back">← 날짜 목록</a>
<div class="card"><h1>{target_date}</h1>
<p class="muted">저장된 데이터 없음. 야간 자동화를 한 번 실행했는지 확인하세요.</p></div>
</body></html>""")

    try:
        payload = jsonlib.loads(row.data)
    except Exception:
        return HTMLResponse("<p>JSON 파싱 실패</p>")

    candidates = payload.get("candidates") or []
    kse_table_json = _load_kse_table_json()

    # 이미 시트(product_sheet)에 있는 키워드 감지 — notes 의 keyword_jp= 매칭
    already_in_sheet: set[str] = set()
    try:
        async with async_session() as session:
            r = await session.execute(
                select(UserData).where(UserData.key == "product_sheet")
            )
            sheet_data_row = r.scalar_one_or_none()
        if sheet_data_row:
            sheet_rows = jsonlib.loads(sheet_data_row.data) or []
            import re as _re
            for sr in sheet_rows:
                notes = sr.get("notes") or ""
                m = _re.search(r"keyword_jp=(\S+)", notes)
                if m:
                    already_in_sheet.add(m.group(1).rstrip(",").rstrip())
    except Exception:
        pass

    body_rows = []
    for i, c in enumerate(candidates, 1):
        margin = c.get("margin") or {}
        ch = c.get("cheapest_domestic") or {}
        kr_ratio_pct = (c.get("kr_ratio") or 0) * 100
        margin_rate = (margin.get("margin_rate") or 0) * 100

        product_url = (ch.get("product_url") or "").replace('"', "&quot;")
        product_name = (ch.get("product_name") or "")[:50]
        product_link = (
            f'<a href="{product_url}" target="_blank">{product_name}</a>'
            if product_url else product_name
        )

        qoo10_search = (
            f'https://www.qoo10.jp/s/?keyword={c.get("keyword_jp", "")}'
        )

        kw_jp_attr = (c.get("keyword_jp") or "").replace('"', "&quot;")
        kw_jp_html = c.get("keyword_jp") or ""
        kw_kr_html = c.get("keyword_kr") or ""
        is_dup = (c.get("keyword_jp") or "") in already_in_sheet
        dup_badge = (
            '<span class="tag tag-bad" title="이미 product_sheet 에 있음">시트✓</span>'
            if is_dup else ""
        )
        row_class = ' class="row-dup"' if is_dup else ""

        # 시트 양식 default 값 (사용자 편집 가능)
        d_name = (ch.get("product_name") or "").replace('"', "&quot;")
        d_url = (ch.get("product_url") or "").replace('"', "&quot;")
        d_img = (ch.get("cover_image_url") or "").replace('"', "&quot;")
        d_price = int(ch.get("price_krw") or 0)
        d_sell_jpy = int(c.get("qoo10_avg_jpy") or 0)
        info_summary = (
            f"검색 {c.get('search_volume', 0):,} · "
            f"KR {kr_ratio_pct:.0f}% · 경쟁 {c.get('competition_intensity', 0):.2f}"
        )
        body_rows.append(f"""
        <tr data-kw="{kw_jp_attr}"{row_class}>
            <td><input type="checkbox" class="row-check"></td>
            <td>{i}</td>
            <td>
              <div><a href="{qoo10_search}" target="_blank">{kw_jp_html}</a> {dup_badge}</div>
              <div class="muted">{kw_kr_html}</div>
              <div class="muted">{info_summary}</div>
            </td>
            <td><input type="text" class="in-name edit-input wide" value="{d_name}"
                       title="상품명 — 직접 수정 가능"></td>
            <td><input type="text" class="in-url edit-input wide" value="{d_url}"
                       title="상품 URL — 직접 수정 가능"></td>
            <td class="right">
              <input type="number" class="in-weight edit-input weight-input num"
                     placeholder="필수" min="0" step="50">
            </td>
            <td class="right">
              <input type="number" class="in-itemprice edit-input num"
                     value="{d_price}" min="0" step="100">
            </td>
            <td class="right">
              <input type="number" class="in-domesticship edit-input num"
                     value="0" min="0" step="100" title="국내 배송비">
            </td>
            <td class="right">
              <input type="number" class="in-packaging edit-input num"
                     value="3000" min="0" step="100" title="KSE 포장+배대지">
            </td>
            <td class="right">
              <input type="number" class="in-selljpy edit-input num"
                     value="{d_sell_jpy}" min="0" step="50" title="엔화 판매가">
            </td>
            <td class="right">
              <input type="number" class="in-rate edit-input num"
                     value="9.5" min="0" step="0.1" title="환율">
            </td>
            <td class="right calc-cost muted">-</td>
            <td class="right calc-revenue muted">-</td>
            <td class="right calc-profit">-</td>
            <td class="right calc-margin">-</td>
            <td class="calc-verdict">-</td>
            <td class="right" style="background:#ecfeff">{c.get('final_score', 0):.2f}</td>
            <td><input type="hidden" class="in-image" value="{d_img}"></td>
        </tr>""")

    table_body = "".join(body_rows) or '<tr><td colspan="18" class="muted">후보 없음</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>{target_date} 자동화 결과</title>
<style>{_BASE_CSS}
.toolbar {{ position: sticky; top: 0; background: #f5f5f5; padding: 0.5rem 0;
           margin-bottom: 0.75rem; z-index: 10; display: flex; gap: 0.5rem; align-items: center; }}
.btn {{ background: #2563eb; color: white; padding: 0.5rem 1rem;
       border-radius: 6px; border: none; cursor: pointer; font-weight: 600; }}
.btn:hover {{ background: #1d4ed8; }}
.btn:disabled {{ background: #9ca3af; cursor: not-allowed; }}
.btn-toast {{ background: #fef3c7; color: #92400e; padding: 0.5rem 1rem;
             border-radius: 6px; font-size: 13px; }}
.edit-input {{ padding: 2px 4px; border: 1px solid #d1d5db;
              border-radius: 4px; font-size: 12px; }}
.edit-input.num {{ width: 80px; text-align: right; }}
.edit-input.wide {{ width: 200px; }}
.weight-input {{ background: #fef9c3; }}
.weight-input:placeholder-shown {{ background: #fee2e2; }}
.edit-input:focus {{ outline: 2px solid #2563eb; }}
.color-good {{ color: #065f46; font-weight: 600; }}
.color-ok   {{ color: #92400e; font-weight: 600; }}
.color-warn {{ color: #b45309; }}
.color-bad  {{ color: #991b1b; font-weight: 600; }}
.row-dup {{ background: #f3f4f6; opacity: 0.7; }}
.row-dup td input.edit-input {{ background: #e5e7eb; }}
table {{ font-size: 12px; }}
th, td {{ vertical-align: middle; }}
</style></head>
<body>
<a href="/api/recommend/auto-collected" class="back">← 날짜 목록</a>
<div class="card">
  <h2>야간 자동화 결과 — {payload.get('date')} (편집 가능 시트)</h2>
  <p class="muted">생성: {payload.get('generated_at')} ·
    마진율 임계: {payload.get('min_margin_rate')} ·
    통과 <strong>{payload.get('count')}개</strong> / 전체 {payload.get('total_candidates')}개</p>
  <p class="muted">상품시트와 동일 양식. 무게·가격·URL·상품명 셀 모두 편집 가능 →
  실시간 마진 재계산 → 체크 후 [시트로 보내기]. /recommend-products 새로고침하면 반영.</p>
</div>

<div class="toolbar">
  <button type="button" class="btn" id="send-btn">선택 항목 시트로 보내기</button>
  <span class="muted" id="select-count">0개 선택</span>
  <span id="result-msg"></span>
</div>

<table>
<thead><tr>
  <th><input type="checkbox" id="check-all" title="전체 선택"></th>
  <th>#</th><th>키워드(JP/KR)</th>
  <th>상품명</th><th>URL</th>
  <th class="right">무게(g)</th>
  <th class="right">상품가(원)</th>
  <th class="right">국내배송</th>
  <th class="right">KSE+포장</th>
  <th class="right">판매가(엔)</th>
  <th class="right">환율</th>
  <th class="right">비용(원)</th>
  <th class="right">매출(원)</th>
  <th class="right">이익(원)</th>
  <th class="right">마진율</th>
  <th>등급</th>
  <th class="right">자동점수</th>
  <th></th>
</tr></thead>
<tbody>{table_body}</tbody>
</table>

<script>
(function () {{
  const KSE_TABLE = {kse_table_json};
  const COMMISSION = 0.135;
  const APPROX_RATE = 10;
  const FREE_THRESHOLD = 20000;

  function lookupKse(weight) {{
    if (weight <= 0) return 0;
    for (const r of KSE_TABLE) {{
      if (weight <= r.weight_g) return r.shipping_krw;
    }}
    return KSE_TABLE.length ? KSE_TABLE[KSE_TABLE.length - 1].shipping_krw : 0;
  }}

  function fmtKrw(n) {{ return Math.round(n).toLocaleString() + '원'; }}

  function verdictTag(mr) {{
    let label, cls;
    if (mr >= 0.30) {{ label = '우수'; cls = 'tag-good'; }}
    else if (mr >= 0.20) {{ label = '양호'; cls = 'tag-good'; }}
    else if (mr >= 0.10) {{ label = '애매'; cls = 'tag-ok'; }}
    else if (mr >= 0)    {{ label = '부족'; cls = 'tag-bad'; }}
    else                 {{ label = '손실'; cls = 'tag-bad'; }}
    return '<span class="tag ' + cls + '">' + label + '</span>';
  }}

  function colorClass(mr) {{
    if (mr >= 0.30) return 'color-good';
    if (mr >= 0.20) return 'color-good';
    if (mr >= 0.10) return 'color-ok';
    if (mr >= 0)    return 'color-warn';
    return 'color-bad';
  }}

  function calcRow(tr) {{
    const get = sel => parseFloat(tr.querySelector(sel)?.value || '0') || 0;
    const w  = get('.in-weight');
    const ip = get('.in-itemprice');
    const ds = get('.in-domesticship');
    const pk = get('.in-packaging');
    const sj = get('.in-selljpy');
    const er = get('.in-rate') || 9.5;

    const purchase = ip + ds;
    const sellKrwForMode = sj * er;
    const free = sellKrwForMode >= FREE_THRESHOLD;
    const shippingCost = free ? lookupKse(w) : 0;
    const commissionKrw = sj * COMMISSION * APPROX_RATE;
    const totalCost = purchase + pk + commissionKrw + shippingCost;
    const revenue = sj * APPROX_RATE;
    const profit = revenue - totalCost;
    const marginRate = sj > 0 ? profit / (sj * er) : 0;

    tr.querySelector('.calc-cost').textContent = fmtKrw(totalCost);
    tr.querySelector('.calc-revenue').textContent = fmtKrw(revenue);
    tr.querySelector('.calc-profit').textContent = fmtKrw(profit);
    tr.querySelector('.calc-profit').className = 'right calc-profit ' + colorClass(marginRate);
    tr.querySelector('.calc-margin').textContent = (marginRate * 100).toFixed(1) + '%';
    tr.querySelector('.calc-margin').className = 'right calc-margin ' + colorClass(marginRate);
    tr.querySelector('.calc-verdict').innerHTML = verdictTag(marginRate);
  }}

  // 모든 행 편집 시 재계산
  document.querySelectorAll('tbody tr').forEach(tr => {{
    tr.querySelectorAll('.edit-input.num, .in-weight').forEach(inp => {{
      inp.addEventListener('input', () => calcRow(tr));
    }});
    calcRow(tr);  // 초기 계산
  }});

  // 체크박스
  const checkAll = document.getElementById('check-all');
  const rowChecks = () => document.querySelectorAll('input.row-check');
  const countEl = document.getElementById('select-count');
  function updateCount() {{
    countEl.textContent = Array.from(rowChecks()).filter(c => c.checked).length + '개 선택';
  }}
  checkAll.addEventListener('change', e => {{
    rowChecks().forEach(c => c.checked = e.target.checked);
    updateCount();
  }});
  rowChecks().forEach(c => c.addEventListener('change', updateCount));

  // 시트로 보내기
  const sendBtn = document.getElementById('send-btn');
  const msgEl = document.getElementById('result-msg');

  sendBtn.addEventListener('click', async () => {{
    const items = [];
    let missingWeight = 0;
    document.querySelectorAll('input.row-check:checked').forEach(cb => {{
      const tr = cb.closest('tr');
      const get = sel => tr.querySelector(sel)?.value || '';
      const getNum = sel => parseFloat(tr.querySelector(sel)?.value || '0') || 0;
      const w = getNum('.in-weight');
      if (!w) missingWeight++;
      items.push({{
        keyword_jp: tr.dataset.kw,
        product_name: get('.in-name'),
        product_name_ko: '',
        product_url: get('.in-url'),
        cover_image_url: get('.in-image'),
        weight_g: w,
        item_price_krw: getNum('.in-itemprice'),
        domestic_shipping_krw: getNum('.in-domesticship'),
        shipping_packaging_krw: getNum('.in-packaging'),
        sell_price_jpy: getNum('.in-selljpy'),
        exchange_rate: getNum('.in-rate') || 9.5,
        shipping_mode: 'auto',
      }});
    }});

    if (items.length === 0) {{
      msgEl.innerHTML = '<span class="btn-toast">선택된 항목이 없습니다</span>';
      return;
    }}
    let warn = '';
    if (missingWeight > 0) warn = '\\n⚠️ 무게 비어있는 행 ' + missingWeight + '개';
    if (!confirm(items.length + '개를 product_sheet 에 추가합니다.' + warn + '\\n진행할까요?')) return;

    sendBtn.disabled = true;
    msgEl.innerHTML = '<span class="btn-toast">전송 중...</span>';
    try {{
      const resp = await fetch('/api/recommend/send-to-sheet/{target_date}', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{items: items}}),
      }});
      const r = await resp.json();
      msgEl.innerHTML = '<span class="btn-toast">' +
        (r.error ? '에러: ' + r.error : (r.message || '추가 ' + r.added + '개')) + '</span>';
    }} catch (e) {{
      msgEl.innerHTML = '<span class="btn-toast">전송 실패: ' + e.message + '</span>';
    }} finally {{
      sendBtn.disabled = false;
    }}
  }});
}})();
</script>
</body></html>"""


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
