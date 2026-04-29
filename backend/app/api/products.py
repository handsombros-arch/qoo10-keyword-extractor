import asyncio
import logging
import traceback
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.db.connection import get_session, async_session
from app.db.sqlite_repo import SQLiteProductRepository
from app.schemas.product import ProductSearchRequest
from app.scrapers.m07_coupang import CoupangScraper
from app.scrapers.m08_naver import NaverShoppingScraper
from app.scrapers.m09_qoo10_products import Qoo10ProductScraper
from app.services.qoo10_export import build_qoo10_excel
from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/products", tags=["products"])
logger = logging.getLogger(__name__)


@router.get("/qoo10")
async def get_qoo10_products(keyword: str = None, session: AsyncSession = Depends(get_session)):
    repo = SQLiteProductRepository(session)
    return await repo.get_qoo10_products(keyword)


@router.post("/domestic/process-images")
async def process_domestic_images(body: dict | None = None):
    """한국 상품 이미지 다운로드 + 비전 평가 + 폴더링 백그라운드 시작.

    body:
      date:        YYYY-MM-DD (기본 오늘)
      keywords_jp: 일본어 키워드 리스트 (선택, None 이면 그 날짜 모든 한국 상품)
      limit:       처리 상한
      reset:       True 면 image_score_overall IS NOT NULL 도 재처리

    동작:
      - DomesticProduct.cover_image_url 다운로드
      - PIL 리사이즈 → 비전 score → image/{date}/{kr_name}/cover.jpg 저장
      - DB UPDATE: image_local_path, image_score_overall, image_score_json
    """
    import asyncio as _asyncio
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel, func as _func, update as _upd
    from app.db.models import DomesticProduct as _DP

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
    raw_limit = body.get("limit")
    limit = int(raw_limit) if raw_limit else None
    do_reset = bool(body.get("reset"))

    # keywords_jp 가 있으면 같은 search_keyword (한국어) 매칭 위해 Keyword 테이블 lookup
    # MVP: keywords_jp 가 일본어 → keyword_kr 변환 필요 → keyword_ko 와 search_keyword 매칭
    target_search_kws: list[str] | None = None
    if keywords_jp:
        from app.db.models import Keyword as _K
        async with async_session() as session:
            kr_rows = await session.execute(
                _sel(_K.keyword_kr).where(_K.keyword_jp.in_(keywords_jp))
                .where(_K.keyword_kr.is_not(None))
                .distinct()
            )
            target_search_kws = [r[0] for r in kr_rows.all() if r[0]]

    reset_count = 0
    if do_reset:
        async with async_session() as session:
            stmt = (
                _upd(_DP)
                .where(_DP.lookup_date == target_date)
                .values(image_local_path=None, image_score_overall=None, image_score_json=None)
            )
            res = await session.execute(stmt)
            await session.commit()
            reset_count = res.rowcount or 0

    # 대상 행 수
    async with async_session() as session:
        stmt = (
            _sel(_func.count())
            .select_from(_DP)
            .where(_DP.lookup_date == target_date)
            .where(_DP.cover_image_url.is_not(None))
            .where(_DP.image_local_path.is_(None))
        )
        if target_search_kws:
            stmt = stmt.where(_DP.search_keyword.in_(target_search_kws))
        total = (await session.execute(stmt)).scalar_one() or 0

    if limit:
        total = min(total, limit)

    if total == 0:
        return {
            "task_id": None, "candidates": 0, "reset_count": reset_count,
            "message": f"{target_date}: 이미지 처리 대상 0개",
        }

    task_id = task_manager.create_task(
        name=f"한국 이미지 처리 ({target_date})", total=total,
    )
    _asyncio.create_task(_run_process_domestic_images(
        task_id, target_date, target_search_kws, limit,
    ))
    return {
        "task_id": task_id, "candidates": total,
        "reset_count": reset_count, "date": str(target_date),
    }


async def _run_process_domestic_images(
    task_id: str, target_date, search_kws: list[str] | None, limit: int | None,
) -> None:
    """백그라운드 — 한국 상품별로 다운로드 + 비전 + 폴더링."""
    from sqlalchemy import select as _sel, update as _upd
    from app.db.models import DomesticProduct as _DP, Keyword as _K
    from app.services.domestic_image_pipeline import download_score_save

    task_manager.start_task(task_id)
    saved = failed = 0

    try:
        # 1) 대상 행
        async with async_session() as session:
            stmt = (
                _sel(_DP.id, _DP.product_name, _DP.cover_image_url,
                     _DP.search_keyword, _DP.source)
                .where(_DP.lookup_date == target_date)
                .where(_DP.cover_image_url.is_not(None))
                .where(_DP.image_local_path.is_(None))
            )
            if search_kws:
                stmt = stmt.where(_DP.search_keyword.in_(search_kws))
            if limit:
                stmt = stmt.limit(limit)
            rows = (await session.execute(stmt)).all()

        # 2) 카테고리 매핑 (search_keyword → category_inferred) — vision prompt 입력용
        kw_to_cat: dict[str, str] = {}
        if rows:
            unique_search_kws = sorted({r[3] for r in rows if r[3]})
            async with async_session() as session:
                kr_rows = await session.execute(
                    _sel(_K.keyword_kr, _K.category_inferred).where(_K.keyword_kr.in_(unique_search_kws))
                )
                for kr, cat in kr_rows.all():
                    if kr and cat and kr not in kw_to_cat:
                        kw_to_cat[kr] = cat

        date_str = str(target_date)
        for idx, (pid, name, url, search_kw, src) in enumerate(rows, 1):
            cat = kw_to_cat.get(search_kw or "", "기타")
            res = await download_score_save(
                product_id=pid,
                cover_url=url,
                product_name_kr=name,
                category=cat,
                date_str=date_str,
                source=src or "src",
            )

            try:
                async with async_session() as session:
                    score = res.get("score") or {}
                    payload = {
                        "image_local_path": res.get("local_path"),
                        "image_score_overall": float(res.get("overall") or 0.0),
                        "image_score_json": _json_dumps(score) if score else None,
                    }
                    await session.execute(
                        _upd(_DP).where(_DP.id == pid).values(**payload)
                    )
                    await session.commit()
            except Exception as e:
                failed += 1
                logger.warning(f"[image_pipeline] DB UPDATE 실패 (pid={pid}): {e}")

            if res.get("ok"):
                saved += 1
            else:
                failed += 1
            tag = f"{res.get('overall', 0):>4.1f}" if res.get("ok") else " ERR"
            note = res.get("note") or ""
            task_manager.update_progress(
                task_id, increment=1,
                message=f"[{idx}/{len(rows)}] {tag} {(name or '')[:30]} ({note[:20]})",
            )

        task_manager.complete_task(
            task_id,
            message=f"완료 — 저장 {saved}, 실패 {failed} (대상 {len(rows)})",
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()


def _json_dumps(obj) -> str:
    import json as _j
    try:
        return _j.dumps(obj, ensure_ascii=False)
    except Exception:
        return ""


@router.post("/qoo10/verify-set-counts")
async def verify_set_counts(body: dict | None = None):
    """마진 N%+ 큐텐 상품의 cover_image_url 비전 카운트 + DB UPDATE.

    body:
      date: YYYY-MM-DD (기본 오늘)
      min_margin_rate: float (기본 2.0 = 200%)
      keywords_jp: list[str] (선택, 한정)
      limit: int (선택)
      exchange_rate: float (기본 9.5)

    동작:
      - lookup_date 큐텐 상품 (cover_image_url 있고 set_count_vision IS NULL) 대상
      - 같은 search_keyword 의 한국 최저가 (DomesticProduct.price_krw 최소) 매칭
      - 큐텐 단가 (price_jpy / set_count) × exchange_rate vs 한국 최저가 → 마진율
      - 마진율 ≥ min_margin_rate 만 비전 호출 → DB UPDATE
    """
    import asyncio as _asyncio
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel, func as _func
    from app.db.models import Qoo10Product as _Q, DomesticProduct as _DP, Keyword as _K

    body = body or {}
    raw_date = body.get("date")
    if raw_date:
        try:
            target_date = _dt.strptime(str(raw_date), "%Y-%m-%d").date()
        except ValueError:
            return {"error": "date 형식: YYYY-MM-DD"}
    else:
        target_date = _date_cls.today()

    min_margin = float(body.get("min_margin_rate", 2.0))
    exchange_rate = float(body.get("exchange_rate", 9.5))
    raw_limit = body.get("limit")
    limit = int(raw_limit) if raw_limit else None
    keywords_jp = body.get("keywords_jp") or []

    # search_keyword 화이트리스트 (jp → kr 매핑)
    search_kws_filter: list[str] | None = None
    if keywords_jp:
        async with async_session() as session:
            kr_rows = await session.execute(
                _sel(_K.keyword_kr).where(_K.keyword_jp.in_(keywords_jp))
                .where(_K.keyword_kr.is_not(None)).distinct()
            )
            search_kws_filter = [r[0] for r in kr_rows.all() if r[0]]

    # 1) 큐텐 후보 + 한국 최저가 매핑 (Python 후처리)
    async with async_session() as session:
        q_stmt = (
            _sel(_Q.id, _Q.product_name, _Q.cover_image_url, _Q.search_keyword,
                 _Q.price_jpy, _Q.set_count)
            .where(_Q.lookup_date == target_date)
            .where(_Q.cover_image_url.is_not(None))
            .where(_Q.price_jpy > 0)
            .where(_Q.set_count_vision.is_(None))
        )
        if search_kws_filter:
            q_stmt = q_stmt.where(_Q.search_keyword.in_(search_kws_filter))
        q_rows = (await session.execute(q_stmt)).all()

        # search_keyword (한국어) → 최저가 매핑 (큐텐 search_keyword 가 일본어, 한국 search_keyword 가 한국어 → keyword_jp/kr 매핑 필요)
        # 현재 큐텐 search_keyword = 일본어, 한국 search_keyword = 한국어
        # 매핑: keyword_jp → keyword_kr 변환
        unique_jp = sorted({r[3] for r in q_rows if r[3]})
        kr_map: dict[str, str] = {}
        if unique_jp:
            kr_rows = await session.execute(
                _sel(_K.keyword_jp, _K.keyword_kr).where(_K.keyword_jp.in_(unique_jp))
                .where(_K.keyword_kr.is_not(None))
            )
            for jp, kr in kr_rows.all():
                if jp and kr and jp not in kr_map:
                    kr_map[jp] = kr

        unique_kr = sorted(set(kr_map.values()))
        # 한국 최저가 dict
        min_price_map: dict[str, float] = {}
        if unique_kr:
            mp_rows = await session.execute(
                _sel(_DP.search_keyword, _func.min(_DP.price_krw))
                .where(_DP.search_keyword.in_(unique_kr))
                .where(_DP.lookup_date == target_date)
                .where(_DP.price_krw > 0)
                .group_by(_DP.search_keyword)
            )
            for kw_kr, p in mp_rows.all():
                if kw_kr and p:
                    min_price_map[kw_kr] = float(p)

    # 2) Python 에서 마진 계산 + 임계값 필터
    candidates: list[dict] = []
    for pid, name, url, search_jp, price_jpy, sc in q_rows:
        sc = sc or 1
        unit_jpy = float(price_jpy) / max(sc, 1)
        unit_krw_equiv = unit_jpy * exchange_rate
        kw_kr = kr_map.get(search_jp or "")
        if not kw_kr:
            continue
        kr_min = min_price_map.get(kw_kr)
        if not kr_min or kr_min <= 0:
            continue
        # 마진율 = (큐텐 단가 환산 - 한국 최저가) / 한국 최저가
        margin = (unit_krw_equiv - kr_min) / kr_min
        if margin < min_margin:
            continue
        candidates.append({
            "id": pid, "name": name, "url": url,
            "price_jpy": price_jpy, "set_count": sc,
            "unit_krw": unit_krw_equiv, "kr_min": kr_min, "margin": margin,
        })

    # 마진율 내림차순
    candidates.sort(key=lambda x: -x["margin"])
    if limit:
        candidates = candidates[:limit]

    if not candidates:
        return {
            "task_id": None, "candidates": 0, "scanned": len(q_rows),
            "message": f"{target_date}: 마진 ≥ {min_margin*100:.0f}% 0개",
        }

    task_id = task_manager.create_task(
        name=f"set_count 비전 검증 ({target_date}, ≥{min_margin*100:.0f}%)",
        total=len(candidates),
    )
    _asyncio.create_task(_run_verify_set_counts(task_id, candidates))
    return {
        "task_id": task_id, "candidates": len(candidates), "scanned": len(q_rows),
        "min_margin_rate": min_margin, "date": str(target_date),
    }


async def _run_verify_set_counts(task_id: str, candidates: list[dict]) -> None:
    """백그라운드 — 각 후보 큐텐 cover 다운로드 + count_packages_in_image."""
    from datetime import datetime as _dt
    from sqlalchemy import update as _upd
    from app.db.models import Qoo10Product as _Q
    from app.services.domestic_image_pipeline import download_to_temp
    from app.services.llm.vision import count_packages_in_image_async
    from pathlib import Path as _P

    task_manager.start_task(task_id)
    matched = mismatched = failed = 0

    try:
        for idx, c in enumerate(candidates, 1):
            pid = c["id"]; url = c["url"]; sc_text = c["set_count"]
            tmp_path = await download_to_temp(url)
            if not tmp_path:
                failed += 1
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(candidates)}] 다운로드 실패: {(c['name'] or '')[:30]}",
                )
                continue

            try:
                vc = await count_packages_in_image_async(tmp_path)
                vis_count = int(vc.get("count", 0) or 0)
                vis_conf = float(vc.get("confidence", 0.0) or 0.0)
            except Exception as e:
                failed += 1
                logger.warning(f"[verify] vision 실패 (pid={pid}): {e}")
                vis_count = 0
                vis_conf = 0.0
            finally:
                try:
                    _P(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

            # DB UPDATE — 비전 결과는 항상 저장 (sc_text 와 다르면 mismatch)
            try:
                async with async_session() as session:
                    await session.execute(
                        _upd(_Q).where(_Q.id == pid).values(
                            set_count_vision=vis_count if vis_count > 0 else None,
                            set_count_vision_confidence=vis_conf if vis_count > 0 else None,
                            set_count_verified_at=_dt.utcnow(),
                        )
                    )
                    await session.commit()
            except Exception as e:
                failed += 1
                logger.warning(f"[verify] DB UPDATE 실패 (pid={pid}): {e}")

            tag = "·"
            if vis_count > 0:
                if vis_count == sc_text:
                    matched += 1
                    tag = "="
                else:
                    mismatched += 1
                    tag = "≠"
            task_manager.update_progress(
                task_id, increment=1,
                message=(
                    f"[{idx}/{len(candidates)}] {tag} text={sc_text} vision={vis_count} "
                    f"conf={vis_conf:.2f} margin={c['margin']*100:.0f}% "
                    f"{(c['name'] or '')[:25]}"
                ),
            )

        task_manager.complete_task(
            task_id,
            message=(
                f"완료 — 일치 {matched}, 불일치 {mismatched}, 실패 {failed} "
                f"(대상 {len(candidates)})"
            ),
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()


@router.post("/qoo10/extract-set-counts")
async def extract_set_counts(body: dict | None = None):
    """큐텐 상품의 set_count 백그라운드 추출.

    body:
      date: YYYY-MM-DD (선택, 기본 오늘)
      limit: int (선택, unique product_name 처리 상한)
      reset: bool (선택, True 면 set_count_source IS NOT NULL 행도 재처리)

    동작:
      - lookup_date 의 qoo10_products 중 set_count_source IS NULL 인 행 대상
      - 같은 product_name 은 1회만 추출 (캐시) → 동일 이름 모든 행 일괄 UPDATE
      - 정규식 1차 → 매칭 실패 시 LLM 폴백 → 1~99 검증 → 폴백 1
    """
    import asyncio as _asyncio
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel, func as _func, and_ as _and, update as _upd
    from app.db.models import Qoo10Product as _Q

    body = body or {}
    raw_date = body.get("date")
    if raw_date:
        try:
            target_date = _dt.strptime(str(raw_date), "%Y-%m-%d").date()
        except ValueError:
            return {"error": "date 형식: YYYY-MM-DD"}
    else:
        target_date = _date_cls.today()

    raw_limit = body.get("limit")
    limit = int(raw_limit) if raw_limit else None
    do_reset = bool(body.get("reset"))

    # reset 옵션: 모든 행을 NULL 로 되돌리고 재추출
    reset_count = 0
    if do_reset:
        async with async_session() as session:
            res = await session.execute(
                _upd(_Q)
                .where(_Q.lookup_date == target_date)
                .values(set_count=1, set_count_source=None)
            )
            await session.commit()
            reset_count = res.rowcount or 0

    # 대상 unique product_name 수
    async with async_session() as session:
        stmt = (
            _sel(_func.count(_func.distinct(_Q.product_name)))
            .where(_Q.lookup_date == target_date)
            .where(_Q.set_count_source.is_(None))
            .where(_Q.product_name.is_not(None))
        )
        unique_count = (await session.execute(stmt)).scalar_one() or 0

    if limit:
        unique_count = min(unique_count, limit)

    if unique_count == 0:
        return {
            "task_id": None,
            "candidates": 0,
            "reset_count": reset_count,
            "message": f"{target_date}: 추출 대상 0개",
        }

    task_id = task_manager.create_task(
        name=f"set_count 추출 ({target_date})",
        total=unique_count,
    )
    _asyncio.create_task(_run_extract_set_counts(task_id, target_date, limit))
    return {
        "task_id": task_id,
        "candidates": unique_count,
        "reset_count": reset_count,
        "date": str(target_date),
    }


async def _run_extract_set_counts(task_id: str, target_date, limit: int | None) -> None:
    """백그라운드 — unique product_name 단위 정규식 1차 + LLM 폴백."""
    from sqlalchemy import select as _sel, update as _upd, and_ as _and
    from app.db.models import Qoo10Product as _Q
    from app.services.llm.set_count import _regex_extract, extract_set_count_async

    task_manager.start_task(task_id)
    regex_n = llm_n = default_n = failed = 0

    try:
        # 1) 대상 product_name → ids + cover URL 매핑 (cover OCR 폴백용)
        async with async_session() as session:
            stmt = (
                _sel(_Q.id, _Q.product_name, _Q.cover_image_url)
                .where(_Q.lookup_date == target_date)
                .where(_Q.set_count_source.is_(None))
                .where(_Q.product_name.is_not(None))
            )
            rows = (await session.execute(stmt)).all()

        name_to_ids: dict[str, list[int]] = {}
        name_to_cover: dict[str, str] = {}
        for pid, name, cover in rows:
            n = (name or "").strip()
            if not n:
                continue
            name_to_ids.setdefault(n, []).append(pid)
            if cover and n not in name_to_cover:
                name_to_cover[n] = cover

        unique_names = list(name_to_ids.keys())
        if limit:
            unique_names = unique_names[:limit]

        ocr_n = 0  # M-3 cover OCR 폴백 hit 카운트

        # 2) 순차 처리: 정규식 → cover OCR 정규식 → LLM 폴백
        for idx, name in enumerate(unique_names, 1):
            count = 1
            source = "default"
            try:
                rx = _regex_extract(name)
                if rx is not None:
                    count = rx
                    source = "regex"
                else:
                    # OCR + LLM 폴백 (시그니처: (count, source) 튜플)
                    count, source = await extract_set_count_async(
                        name, cover_image_url=name_to_cover.get(name)
                    )
            except Exception:
                failed += 1
                source = "default"
                count = 1

            if source == "regex":
                regex_n += 1
            elif source in ("regex_ocr", "llm_with_ocr"):
                ocr_n += 1
                if source == "llm_with_ocr":
                    llm_n += 1  # LLM 도 호출했으니 카운트
            elif source == "llm":
                llm_n += 1
            else:
                default_n += 1

            ids = name_to_ids[name]
            try:
                async with async_session() as session:
                    await session.execute(
                        _upd(_Q)
                        .where(_Q.id.in_(ids))
                        .values(set_count=count, set_count_source=source)
                    )
                    await session.commit()
            except Exception:
                failed += 1

            tag = "★" if count > 1 else "·"
            task_manager.update_progress(
                task_id, increment=1,
                message=f"[{idx}/{len(unique_names)}] {tag}{count} ({source}) {name[:30]}",
            )

        task_manager.complete_task(
            task_id,
            message=(
                f"완료 — 정규식 {regex_n}, OCR {ocr_n}, LLM {llm_n}, 단일 {default_n}, "
                f"실패 {failed} (unique {len(unique_names)})"
            ),
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()


@router.get("/domestic")
async def get_domestic_products(source: str = None, session: AsyncSession = Depends(get_session)):
    repo = SQLiteProductRepository(session)
    return await repo.get_domestic_products(source)


@router.post("/qoo10")
async def search_qoo10_products(req: ProductSearchRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    async def _task():
        try:
            scraper = Qoo10ProductScraper(browser_manager, task_manager)
            result = await scraper.run(keyword=req.keyword)
            if "products" in result:
                async with async_session() as session:
                    repo = SQLiteProductRepository(session)
                    await repo.save_qoo10_products(result["products"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started"}


@router.post("/coupang")
async def search_coupang_products(req: ProductSearchRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    async def _task():
        try:
            scraper = CoupangScraper(browser_manager, task_manager)
            result = await scraper.run(keyword=req.keyword)
            if "products" in result:
                async with async_session() as session:
                    repo = SQLiteProductRepository(session)
                    await repo.save_domestic_products(result["products"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started"}


class Qoo10ExportRow(BaseModel):
    product_name: str = ""
    product_name_ko: str = ""
    sell_price_jpy: float = 0
    cover_image_url: str = ""
    weight_g: float = 0
    notes: str = ""
    source: str = ""
    search_keyword: str = ""
    # Phase 4-B — 큐텐 등록 LLM 콘텐츠 (옵셔널)
    qoo10_title_jp: str = ""
    qoo10_tags: list[str] = []
    qoo10_option_name: str = ""
    qoo10_marketing: list[str] = []


class Qoo10ExportDefaults(BaseModel):
    category_number: str = ""
    brand_number: str = ""
    shipping_number: str = ""
    end_date: str = ""        # YYYY-MM-DD
    quantity: int = 100
    available_shipping_date: int = 7
    item_condition_type: str = "1"  # 1=새상품
    origin_type: str = "2"          # 2=해외
    origin_country_id: str = "KR"
    item_status: str = "Y"
    under18s_display: str = "N"
    default_description: str = ""


class Qoo10ExportRequest(BaseModel):
    rows: list[Qoo10ExportRow]
    defaults: Qoo10ExportDefaults


@router.post("/export-qoo10")
async def export_qoo10(req: Qoo10ExportRequest):
    """큐텐 대량등록 엑셀 양식(Qoo10_EditItemList.xlsx)에 맞춰 채운 xlsx 반환."""
    rows_data = [r.dict() for r in req.rows]
    defaults_data = req.defaults.dict()
    xlsx_bytes = build_qoo10_excel(rows_data, defaults_data)

    filename = f"Qoo10_EditItemList_{date.today()}.xlsx"
    return StreamingResponse(
        iter([xlsx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/naver")
async def search_naver_products(req: ProductSearchRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    async def _task():
        try:
            scraper = NaverShoppingScraper(browser_manager, task_manager)
            result = await scraper.run(keyword=req.keyword)
            if "products" in result:
                async with async_session() as session:
                    repo = SQLiteProductRepository(session)
                    await repo.save_domestic_products(result["products"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started"}


@router.post("/qoo10/translate-names")
async def translate_qoo10_names(body: dict | None = None):
    """큐텐 상품명 일본어 → 한국어 번역 (백그라운드).

    body:
      date:  YYYY-MM-DD (선택, 기본 오늘)
      limit: int (선택, unique product_name 처리 상한)
      reset: bool (True 면 product_name_ko IS NOT NULL 도 재번역)

    동작:
      - lookup_date 의 qoo10_products 중 product_name_ko IS NULL & product_name IS NOT NULL 대상
      - 같은 product_name 1회만 LLM 호출 (translate.py 가 translation_cache 도 활용)
      - 동일 이름 모든 행 일괄 UPDATE
    """
    import asyncio as _asyncio
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel, func as _func, update as _upd
    from app.db.models import Qoo10Product as _Q

    body = body or {}
    raw_date = body.get("date")
    if raw_date:
        try:
            target_date = _dt.strptime(str(raw_date), "%Y-%m-%d").date()
        except ValueError:
            return {"error": "date 형식: YYYY-MM-DD"}
    else:
        target_date = _date_cls.today()

    raw_limit = body.get("limit")
    limit = int(raw_limit) if raw_limit else None
    do_reset = bool(body.get("reset"))

    reset_count = 0
    if do_reset:
        async with async_session() as session:
            res = await session.execute(
                _upd(_Q).where(_Q.lookup_date == target_date).values(product_name_ko=None)
            )
            await session.commit()
            reset_count = res.rowcount or 0

    async with async_session() as session:
        stmt = (
            _sel(_func.count(_func.distinct(_Q.product_name)))
            .where(_Q.lookup_date == target_date)
            .where(_Q.product_name_ko.is_(None))
            .where(_Q.product_name.is_not(None))
        )
        unique_count = (await session.execute(stmt)).scalar_one() or 0

    if limit:
        unique_count = min(unique_count, limit)

    if unique_count == 0:
        return {
            "task_id": None, "candidates": 0, "reset_count": reset_count,
            "message": f"{target_date}: 번역 대상 0개",
        }

    task_id = task_manager.create_task(
        name=f"큐텐 상품명 번역 ({target_date})", total=unique_count,
    )
    _asyncio.create_task(_run_translate_qoo10_names(task_id, target_date, limit))
    return {
        "task_id": task_id, "candidates": unique_count,
        "reset_count": reset_count, "date": str(target_date),
    }


async def _run_translate_qoo10_names(task_id: str, target_date, limit: int | None) -> None:
    """백그라운드 — unique product_name 단위 번역 + 동일 이름 일괄 UPDATE."""
    from sqlalchemy import select as _sel, update as _upd
    from app.db.models import Qoo10Product as _Q
    from app.services.llm.translate import translate_jp_to_ko_async

    task_manager.start_task(task_id)
    llm_n = failed = 0

    try:
        async with async_session() as session:
            stmt = (
                _sel(_Q.id, _Q.product_name)
                .where(_Q.lookup_date == target_date)
                .where(_Q.product_name_ko.is_(None))
                .where(_Q.product_name.is_not(None))
            )
            rows = (await session.execute(stmt)).all()

        name_to_ids: dict[str, list[int]] = {}
        for pid, name in rows:
            name_to_ids.setdefault(name, []).append(pid)

        unique_names = list(name_to_ids.keys())
        if limit:
            unique_names = unique_names[:limit]

        for idx, name in enumerate(unique_names, 1):
            try:
                ko = await translate_jp_to_ko_async(name)
            except Exception as e:
                logger.warning(f"[translate] LLM 실패 (name={name[:30]!r}): {e}")
                ko = None

            if not ko:
                failed += 1
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(unique_names)}] 실패: {name[:35]}",
                )
                continue

            try:
                async with async_session() as session:
                    await session.execute(
                        _upd(_Q)
                        .where(_Q.id.in_(name_to_ids[name]))
                        .values(product_name_ko=ko)
                    )
                    await session.commit()
                llm_n += 1
            except Exception as e:
                failed += 1
                logger.warning(f"[translate] DB UPDATE 실패: {e}")
                continue

            task_manager.update_progress(
                task_id, increment=1,
                message=f"[{idx}/{len(unique_names)}] {name[:25]} → {ko[:30]}",
            )

        task_manager.complete_task(
            task_id,
            message=f"완료 — 번역 {llm_n}, 실패 {failed} (unique {len(unique_names)})",
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()


@router.post("/domestic/scrape-details")
async def scrape_domestic_details(body: dict | None = None):
    """매칭된 한국 상품의 옵션/배송비/이미지 채움 (백그라운드).

    body:
      date:           YYYY-MM-DD (기본 오늘)
      only_accepted:  bool (기본 True — DomesticMatchCandidate.decision='accepted' 만)
      sources:        list[str] (기본 ["naver","coupang"])
      limit:          int (전체 상한)
      reset:          bool (True 면 detail_scraped_at IS NOT NULL 도 재처리)
      mode:           "api_only" (기본, 사장님 결정 A — 검색 API 데이터로 옵션 1건만)
                      "scrape" (Playwright/Scrapling 으로 상세 진입 시도 — 봇 차단 다발)

    api_only 모드 (기본):
      - 상세 페이지 진입 X. m08(네이버 API) / m07(쿠팡 검색) 결과를 그대로 활용.
      - DomesticProduct.price_krw → DomesticProductOption "default" 옵션 1건 INSERT.
      - shipping_kind="unknown", detail_image_paths=None.
      - PHASE2_DETAIL_SCRAPER.md 의 4가지 옵션 中 A 결정으로 단기 진행.
    """
    import asyncio as _asyncio
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel, update as _upd
    from app.db.models import DomesticProduct as _DP, DomesticMatchCandidate as _DMC

    body = body or {}
    raw_date = body.get("date")
    if raw_date:
        try:
            target_date = _dt.strptime(str(raw_date), "%Y-%m-%d").date()
        except ValueError:
            return {"error": "date 형식: YYYY-MM-DD"}
    else:
        target_date = _date_cls.today()

    only_accepted = body.get("only_accepted", True)
    sources = body.get("sources") or ["naver", "coupang"]
    raw_limit = body.get("limit")
    limit = int(raw_limit) if raw_limit else None
    do_reset = bool(body.get("reset"))
    mode = (body.get("mode") or "api_only").lower()
    if mode not in ("api_only", "scrape"):
        return {"error": f"mode 는 'api_only' 또는 'scrape' (받음: {mode!r})"}

    # 대상 한국 상품 id + price_krw + cover_image_url (api_only 모드용)
    async with async_session() as session:
        cols = (_DP.id, _DP.source, _DP.product_name, _DP.product_url,
                _DP.price_krw, _DP.cover_image_url)
        if only_accepted:
            stmt = (
                _sel(*cols)
                .join(_DMC, _DMC.domestic_product_id == _DP.id)
                .where(_DP.lookup_date == target_date)
                .where(_DP.product_url.is_not(None))
                .where(_DP.source.in_(sources))
                .where(_DMC.decision == "accepted")
                .distinct()
            )
        else:
            stmt = (
                _sel(*cols)
                .where(_DP.lookup_date == target_date)
                .where(_DP.product_url.is_not(None))
                .where(_DP.source.in_(sources))
            )
        if not do_reset:
            stmt = stmt.where(_DP.detail_scraped_at.is_(None))
        rows = (await session.execute(stmt)).all()

    if limit:
        rows = list(rows)[:limit]

    if not rows:
        return {
            "task_id": None, "candidates": 0,
            "message": f"{target_date}: 처리 대상 0건 (only_accepted={only_accepted}, sources={sources})",
        }

    task_id = task_manager.create_task(
        name=f"한국 옵션 채움 [{mode}] ({target_date}, {len(rows)}건)",
        total=len(rows),
    )
    if mode == "api_only":
        _asyncio.create_task(_run_fill_from_api(task_id, rows, str(target_date)))
    else:
        _asyncio.create_task(_run_scrape_details(task_id, rows, str(target_date)))
    return {
        "task_id": task_id, "candidates": len(rows),
        "mode": mode,
        "only_accepted": only_accepted, "sources": sources,
        "date": str(target_date),
    }


async def _run_fill_from_api(task_id: str, rows: list, date_str: str) -> None:
    """api_only 모드 — 검색 API 결과(price_krw)를 옵션 1건으로 INSERT.

    상세 페이지 진입 X. PHASE2_DETAIL_SCRAPER.md A 결정.
    옵션 N개 / 배송비 / 누끼·내용물 이미지는 Phase 2.5 (모바일 API 등) 에서.
    """
    from datetime import datetime as _dt
    from sqlalchemy import update as _upd, delete as _del
    from app.db.models import (
        DomesticProduct as _DP, DomesticProductOption as _DPO,
    )

    task_manager.start_task(task_id)
    ok_n = skip_n = fail_n = 0

    try:
        for idx, (did, src, name, url, price_krw, cover_url) in enumerate(rows, 1):
            try:
                async with async_session() as db:
                    # 옵션 — 기존 행 삭제 후 default 1건만 INSERT (price_krw 가 있을 때만)
                    await db.execute(_del(_DPO).where(_DPO.domestic_product_id == did))
                    if price_krw and int(price_krw) > 0:
                        db.add(_DPO(
                            domestic_product_id=did,
                            option_name="default",
                            option_price_krw=int(price_krw),
                            in_stock=1,
                        ))
                    # 상위 컬럼 — shipping unknown, detail_scraped_at 마킹
                    await db.execute(_upd(_DP).where(_DP.id == did).values(
                        shipping_kind="unknown",
                        shipping_amount=None,
                        shipping_threshold=None,
                        detail_image_paths=None,
                        detail_scraped_at=_dt.utcnow(),
                    ))
                    await db.commit()
            except Exception as e:
                fail_n += 1
                logger.warning(f"[fill-api] DB UPDATE 실패 d={did}: {e}")
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(rows)}] DB-FAIL d={did}",
                )
                continue

            if price_krw and int(price_krw) > 0:
                ok_n += 1
                tag = "OK"
            else:
                skip_n += 1
                tag = "SKIP"  # price_krw 가 없는 케이스 (m07 검색 누락 등)

            task_manager.update_progress(
                task_id, increment=1,
                message=(
                    f"[{idx}/{len(rows)}] {tag} d={did} src={src} "
                    f"price={price_krw or 0} {(name or '')[:25]}"
                ),
            )

        task_manager.complete_task(
            task_id,
            message=f"완료 — OK {ok_n}, SKIP {skip_n}, 실패 {fail_n} (대상 {len(rows)})",
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()


async def _run_scrape_details(task_id: str, rows: list, date_str: str) -> None:
    """백그라운드 — 한 상품씩 상세 진입 → 옵션/배송비/이미지 + DB UPDATE.

    Playwright Browser 한 번만 launch (DomesticDetailSession async-with) — 각 상품
    새 컨텍스트로 격리. 끝나면 close.
    """
    import json as _json
    from datetime import datetime as _dt
    from sqlalchemy import update as _upd, delete as _del
    from app.db.models import (
        DomesticProduct as _DP, DomesticProductOption as _DPO,
    )
    from app.scrapers.m_domestic_details import (
        scrape_domestic_detail, DomesticDetailSession,
    )

    task_manager.start_task(task_id)
    ok_n = fail_n = 0

    try:
        async with DomesticDetailSession() as pw_session:
            for idx, (did, src, name, url, _price_krw, _cover_url) in enumerate(rows, 1):
                try:
                    res = await scrape_domestic_detail(
                        session=pw_session,
                        domestic_id=did,
                        source=src or "",
                        product_url=url,
                        product_name_kr=name or "",
                        date_str=date_str,
                    )
                except Exception as e:
                    fail_n += 1
                    logger.warning(f"[detail] 호출 실패 d={did}: {e}")
                    task_manager.update_progress(
                        task_id, increment=1,
                        message=f"[{idx}/{len(rows)}] FAIL d={did} ({type(e).__name__})",
                    )
                    continue

                try:
                    async with async_session() as db:
                        await db.execute(_del(_DPO).where(_DPO.domestic_product_id == did))
                        for opt in res.get("options", []):
                            db.add(_DPO(
                                domestic_product_id=did,
                                option_name=str(opt.get("name") or "default")[:200],
                                option_price_krw=int(opt.get("price_krw") or 0) or None,
                                in_stock=1 if opt.get("in_stock", True) else 0,
                            ))
                        sh = res.get("shipping", {})
                        payload = {
                            "shipping_kind": sh.get("kind") or None,
                            "shipping_amount": sh.get("amount"),
                            "shipping_threshold": sh.get("threshold"),
                            "detail_image_paths": _json.dumps(res.get("extra_image_paths", []), ensure_ascii=False)
                                if res.get("extra_image_paths") else None,
                            "detail_scraped_at": _dt.utcnow(),
                        }
                        await db.execute(_upd(_DP).where(_DP.id == did).values(**payload))
                        await db.commit()
                except Exception as e:
                    fail_n += 1
                    logger.warning(f"[detail] DB UPDATE 실패 d={did}: {e}")
                    task_manager.update_progress(
                        task_id, increment=1,
                        message=f"[{idx}/{len(rows)}] DB-FAIL d={did}",
                    )
                    continue

                if res.get("ok"):
                    ok_n += 1
                else:
                    fail_n += 1

                opt_n = len(res.get("options", []))
                ext_n = len(res.get("extra_image_paths", []))
                sh_kind = (res.get("shipping") or {}).get("kind") or "?"
                tag = "OK" if res.get("ok") else "EMPTY"
                task_manager.update_progress(
                    task_id, increment=1,
                    message=(
                        f"[{idx}/{len(rows)}] {tag} d={did} "
                        f"opts={opt_n} img={ext_n} ship={sh_kind} "
                        f"({(res.get('note') or '')[:25]})"
                    ),
                )

        task_manager.complete_task(
            task_id,
            message=f"완료 — OK {ok_n}, 실패 {fail_n} (대상 {len(rows)})",
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()


@router.post("/domestic/extract-weights")
async def extract_domestic_weights(body: dict | None = None):
    """한국 상품의 무게 추출 (상품명 정규식) + 200g 패키지 룰 (Phase 4-A).

    body:
      date:          YYYY-MM-DD (기본 오늘)
      only_accepted: bool (기본 True — DomesticMatchCandidate.decision='accepted')
      packaging_g:   float (기본 200.0)
      reset:         bool (True 면 weight_g 채워진 행도 재처리)
    """
    import asyncio as _asyncio
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel
    from app.db.models import DomesticProduct as _DP, DomesticMatchCandidate as _DMC

    body = body or {}
    raw_date = body.get("date")
    if raw_date:
        try:
            target_date = _dt.strptime(str(raw_date), "%Y-%m-%d").date()
        except ValueError:
            return {"error": "date 형식: YYYY-MM-DD"}
    else:
        target_date = _date_cls.today()

    only_accepted = body.get("only_accepted", True)
    packaging_g = float(body.get("packaging_g", 200.0))
    do_reset = bool(body.get("reset"))

    # 한국 d_id 와 매칭 큐텐 q.product_name(jp) + product_name_ko 도 함께 SELECT.
    # 한국 product_name 에는 무게 정보 거의 없음 — 큐텐 상품명이 핵심 소스.
    from app.db.models import Qoo10Product as _Q

    async with async_session() as session:
        if only_accepted:
            stmt = (
                _sel(
                    _DP.id, _DP.product_name,
                    _Q.product_name.label("q_name"),
                    _Q.product_name_ko.label("q_name_ko"),
                    _DP.cover_image_url.label("cover_url"),
                )
                .join(_DMC, _DMC.domestic_product_id == _DP.id)
                .join(_Q, _Q.id == _DMC.qoo10_product_id)
                .where(_DP.lookup_date == target_date)
                .where(_DP.product_name.is_not(None))
                .where(_DMC.decision == "accepted")
                .distinct()
            )
        else:
            stmt = (
                _sel(
                    _DP.id, _DP.product_name,
                    _DP.product_name.label("q_name"),  # 매칭 없으면 한국 이름만
                    _DP.product_name.label("q_name_ko"),
                    _DP.cover_image_url.label("cover_url"),
                )
                .where(_DP.lookup_date == target_date)
                .where(_DP.product_name.is_not(None))
            )
        if not do_reset:
            stmt = stmt.where(_DP.weight_g.is_(None))
        rows = (await session.execute(stmt)).all()

    if not rows:
        return {
            "task_id": None, "candidates": 0,
            "message": f"{target_date}: 처리 대상 0건 (only_accepted={only_accepted})",
        }

    task_id = task_manager.create_task(
        name=f"한국 상품 무게 추출 ({target_date}, {len(rows)}건, +{packaging_g:.0f}g)",
        total=len(rows),
    )
    _asyncio.create_task(_run_extract_weights(task_id, rows, packaging_g))
    return {
        "task_id": task_id, "candidates": len(rows),
        "only_accepted": only_accepted, "packaging_g": packaging_g,
        "date": str(target_date),
    }


async def _run_extract_weights(task_id: str, rows: list, packaging_g: float) -> None:
    """백그라운드 — 상품명 정규식 + cover OCR + LLM 폴백 → +200g 룰 → DB UPDATE.

    추출 우선순위:
      ① 매칭 큐텐 jp/ko 또는 한국 product_name 정규식 (regex)
      ② cover image OCR + 정규식 재시도 (regex_ocr)
      ③ LLM 추론 (qwen2.5:7b set_count 모델 재사용) — 카테고리 기반 평균값
    """
    from sqlalchemy import update as _upd
    from app.db.models import DomesticProduct as _DP
    from app.services.weight_extractor import apply_packaging_rule, extract_weight_async

    task_manager.start_task(task_id)
    by_source = {"regex": 0, "regex_ocr": 0, "llm": 0, "default": 0}

    try:
        for idx, row in enumerate(rows, 1):
            # row 는 named tuple — cover_url 추가됨
            did, name, q_name, q_name_ko, cover_url = row
            try:
                raw_g, source = await extract_weight_async(
                    product_name=name or "",
                    qoo10_jp=q_name or "",
                    qoo10_ko=q_name_ko or "",
                    cover_image_url=cover_url or "",
                    category="기타",
                )
            except Exception as e:
                logger.debug(f"[weight] extract 실패 d={did}: {e}")
                raw_g, source = None, "default"

            final_g = apply_packaging_rule(raw_g, packaging_g) if raw_g is not None else None
            by_source[source] = by_source.get(source, 0) + 1

            try:
                async with async_session() as db:
                    await db.execute(_upd(_DP).where(_DP.id == did).values(
                        weight_g=final_g, weight_source=source,
                    ))
                    await db.commit()
            except Exception as e:
                logger.warning(f"[weight] DB UPDATE 실패 d={did}: {e}")

            if final_g is not None:
                tag = f"{source[:5].upper()} raw={raw_g:.0f} +200={final_g:.0f}"
            else:
                tag = "MISS"
            task_manager.update_progress(
                task_id, increment=1,
                message=f"[{idx}/{len(rows)}] {tag} d={did} {(name or '')[:30]}",
            )

        matched = sum(v for k, v in by_source.items() if k != "default")
        task_manager.complete_task(
            task_id,
            message=(
                f"완료 — regex {by_source['regex']}, OCR {by_source['regex_ocr']}, "
                f"LLM {by_source['llm']}, 미매칭 {by_source['default']} "
                f"({100*matched//max(len(rows),1)}% / 대상 {len(rows)})"
            ),
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()


@router.post("/qoo10/generate-content")
async def generate_qoo10_listing_content(body: dict | None = None):
    """큐텐 등록용 콘텐츠 LLM 생성 (Phase 4-B).

    body:
      date:           YYYY-MM-DD (기본 오늘)
      only_accepted:  bool (기본 True — 매칭된 큐텐 상품만)
      limit:          int
      reset:          bool (True 면 qoo10_content_generated_at 채워진 행도 재처리)

    출력 컬럼:
      qoo10_title_jp / qoo10_tags(JSON) / qoo10_option_name / qoo10_marketing(JSON)
    """
    import asyncio as _asyncio
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel
    from app.db.models import (
        Qoo10Product as _Q, DomesticMatchCandidate as _DMC,
        DomesticProduct as _DP, Keyword as _K,
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

    only_accepted = body.get("only_accepted", True)
    raw_limit = body.get("limit")
    limit = int(raw_limit) if raw_limit else None
    do_reset = bool(body.get("reset"))
    # keywords_jp body 인자 — 있으면 lookup_date 무시하고 keyword 매칭 (시트에서 호출 케이스)
    keywords_jp = body.get("keywords_jp") or []

    # 대상 큐텐 상품 + 매칭 한국 상품명 + 카테고리
    async with async_session() as session:
        cols = (
            _Q.id, _Q.product_name, _Q.product_name_ko, _Q.search_keyword,
            _DP.product_name.label("d_name"), _DP.price_krw.label("d_price"),
            _K.category_inferred.label("cat"),
        )
        if only_accepted:
            stmt = (
                _sel(*cols)
                .join(_DMC, _DMC.qoo10_product_id == _Q.id)
                .join(_DP, _DP.id == _DMC.domestic_product_id)
                .outerjoin(_K, _K.keyword_jp == _Q.search_keyword)
                .where(_DMC.decision == "accepted")
                .distinct()
            )
        else:
            # outerjoin 으로 row 곱해지는 것 방지 — distinct 필수
            stmt = (
                _sel(*cols)
                .outerjoin(_DP, _DP.search_keyword == _Q.product_name_ko)
                .outerjoin(_K, _K.keyword_jp == _Q.search_keyword)
                .distinct()
            )
        # date 필터 — keywords_jp 있으면 무시 (사장님이 시트에서 특정 키워드 지정 → 모든 날짜)
        if keywords_jp:
            stmt = stmt.where(_Q.search_keyword.in_(keywords_jp))
        else:
            stmt = stmt.where(_Q.lookup_date == target_date)
        if not do_reset:
            stmt = stmt.where(_Q.qoo10_content_generated_at.is_(None))
        rows = (await session.execute(stmt)).all()

    # 큐텐 product id 단일 기준 dedup (outerjoin 으로 row 곱해진 것 정리)
    seen_qids: set = set()
    unique_rows = []
    for r in rows:
        qid = r[0]
        if qid in seen_qids:
            continue
        seen_qids.add(qid)
        unique_rows.append(r)
    rows = unique_rows

    if limit:
        rows = list(rows)[:limit]

    if not rows:
        return {
            "task_id": None, "candidates": 0,
            "message": f"{target_date}: 처리 대상 0건 (only_accepted={only_accepted})",
        }

    task_id = task_manager.create_task(
        name=f"큐텐 콘텐츠 생성 ({target_date}, {len(rows)}건)", total=len(rows),
    )
    _asyncio.create_task(_run_generate_qoo10_content(task_id, rows))
    return {
        "task_id": task_id, "candidates": len(rows),
        "only_accepted": only_accepted, "date": str(target_date),
    }


async def _run_generate_qoo10_content(task_id: str, rows: list) -> None:
    """백그라운드 — 큐텐 등록 콘텐츠 LLM 생성 + DB UPDATE."""
    import json as _json
    from datetime import datetime as _dt
    from sqlalchemy import update as _upd
    from app.db.models import Qoo10Product as _Q
    from app.services.llm.qoo10_content import generate_qoo10_content_async

    task_manager.start_task(task_id)
    ok_n = fail_n = 0

    try:
        for idx, row in enumerate(rows, 1):
            qid, q_name, q_ko, q_kw, d_name, d_price, cat = row
            # 입력: 한국 상품명 우선 (실제 등록 대상), 없으면 큐텐 ko, 그것도 없으면 jp
            input_name = (d_name or q_ko or q_name or "").strip()
            if not input_name:
                fail_n += 1
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(rows)}] SKIP q={qid} (빈 이름)",
                )
                continue

            try:
                res = await generate_qoo10_content_async(
                    product_name_kr=input_name,
                    category=cat or "기타",
                    price_krw=int(d_price or 0) or None,
                    option_name_kr="default",
                )
            except Exception as e:
                fail_n += 1
                logger.warning(f"[qoo10_content] LLM 실패 q={qid}: {e}")
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(rows)}] FAIL q={qid} ({type(e).__name__})",
                )
                continue

            if not res.get("ok"):
                fail_n += 1
                # ok=False 라도 부분 생성된 데이터는 저장
                pass
            else:
                ok_n += 1

            try:
                async with async_session() as db:
                    await db.execute(_upd(_Q).where(_Q.id == qid).values(
                        qoo10_title_jp=res.get("title_jp") or None,
                        qoo10_tags=_json.dumps(res.get("tags") or [], ensure_ascii=False),
                        qoo10_option_name=res.get("option_name") or None,
                        qoo10_marketing=_json.dumps(res.get("marketing_points") or [], ensure_ascii=False),
                        qoo10_content_generated_at=_dt.utcnow(),
                    ))
                    await db.commit()
            except Exception as e:
                logger.warning(f"[qoo10_content] DB UPDATE 실패 q={qid}: {e}")

            tag = "OK" if res.get("ok") else "PARTIAL"
            title_short = (res.get("title_jp") or "")[:25]
            tags_n = len(res.get("tags") or [])
            mkt_n = len(res.get("marketing_points") or [])
            task_manager.update_progress(
                task_id, increment=1,
                message=(
                    f"[{idx}/{len(rows)}] {tag} q={qid} title={title_short!r} "
                    f"tags={tags_n} mkt={mkt_n}"
                ),
            )

        task_manager.complete_task(
            task_id,
            message=f"완료 — OK {ok_n}, 실패/부분 {fail_n} (대상 {len(rows)})",
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()
