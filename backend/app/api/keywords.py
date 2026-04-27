import asyncio
import re
import traceback
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.config import settings
from app.db.connection import get_session, async_session
from app.db.sqlite_repo import SQLiteKeywordRepository, SQLiteBidRepository
from app.schemas.keyword import TrendKeywordRequest, RelatedKeywordRequest
from app.scrapers.m02_trend_keywords import TrendKeywordScraper, CATEGORIES
from app.scrapers.m04_bid_results import BidResultScraper
from app.scrapers.m05_related_keywords import RelatedKeywordScraper
from app.services.task_manager import task_manager
from app.services.translation import translate_batch

router = APIRouter(prefix="/api/keywords", tags=["keywords"])


@router.get("")
async def list_keywords(session: AsyncSession = Depends(get_session)):
    repo = SQLiteKeywordRepository(session)
    return await repo.get_keywords()


@router.delete("/{keyword_id}")
async def delete_keyword(keyword_id: int, session: AsyncSession = Depends(get_session)):
    repo = SQLiteKeywordRepository(session)
    await repo.delete_keyword(keyword_id)
    return {"status": "deleted"}


@router.get("/dates")
async def list_keyword_dates(session: AsyncSession = Depends(get_session)):
    repo = SQLiteKeywordRepository(session)
    return await repo.list_dates()


@router.get("/categories")
async def list_keyword_categories(session: AsyncSession = Depends(get_session)):
    """DB에 등록된 카테고리 목록과 각 카테고리의 키워드 수."""
    from sqlalchemy import select as sa_select, func as sa_func
    from app.db.models import Keyword
    stmt = (
        sa_select(Keyword.category, sa_func.count(Keyword.id))
        .group_by(Keyword.category)
        .order_by(Keyword.category)
    )
    result = await session.execute(stmt)
    return [
        {"category": row[0] or "(미분류)", "count": row[1]}
        for row in result.all()
    ]


@router.post("/classify-categories")
async def classify_categories(body: dict | None = None):
    """LLM 카테고리 분류 백그라운드 시작.

    body:
      date:  'YYYY-MM-DD' (선택, 기본 오늘)
      limit: int (선택, unique 키워드 처리 상한)

    동작:
      - 해당 날짜의 keywords 중 category_inferred IS NULL/'' 인 행 대상
      - 같은 (keyword_kr or keyword_jp) 는 1회만 LLM 호출 → 동일 텍스트의 모든 행 일괄 UPDATE
      - 진행상황: task_manager 로 폴링 가능
    """
    import asyncio as _asyncio
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel, func as _func, and_ as _and, or_ as _or
    from app.db.models import Keyword as _Keyword

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

    # reset_label: 이 라벨로 분류된 행을 NULL 로 되돌리고 재분류 대상에 포함
    # 예: reset_label="기타" → 기존에 "기타" 로 잘못 박힌 행들을 다시 시도
    reset_label = (body.get("reset_label") or "").strip()
    reset_count = 0
    if reset_label:
        from sqlalchemy import update as _upd_reset
        from app.db.models import Keyword as _K_reset
        async with async_session() as session:
            res = await session.execute(
                _upd_reset(_K_reset)
                .where(_K_reset.lookup_date == target_date)
                .where(_K_reset.category_inferred == reset_label)
                .values(category_inferred=None)
            )
            await session.commit()
            reset_count = res.rowcount or 0

    # 대상 unique 키워드 수 카운트 (task total)
    async with async_session() as session:
        stmt = (
            _sel(_func.count(_func.distinct(_func.coalesce(_Keyword.keyword_kr, _Keyword.keyword_jp))))
            .where(
                _and(
                    _Keyword.lookup_date == target_date,
                    _or(_Keyword.category_inferred.is_(None), _Keyword.category_inferred == ""),
                )
            )
        )
        unique_count = (await session.execute(stmt)).scalar_one() or 0

    if limit:
        unique_count = min(unique_count, limit)

    if unique_count == 0:
        return {
            "task_id": None,
            "candidates": 0,
            "reset_count": reset_count,
            "message": f"{target_date}: 분류 대상 0개",
        }

    task_id = task_manager.create_task(
        name=f"카테고리 분류 ({target_date})",
        total=unique_count,
    )
    _asyncio.create_task(_run_classify_categories(task_id, target_date, limit))
    return {
        "task_id": task_id,
        "candidates": unique_count,
        "reset_count": reset_count,
        "date": str(target_date),
    }


async def _run_classify_categories(task_id: str, target_date, limit: int | None) -> None:
    """백그라운드 분류 실행 — 카테고리 + 브랜드 동시.

    unique 키워드 단위로 LLM 호출 (category + brand 각각). 같은 텍스트의 모든 행 UPDATE.
    """
    from sqlalchemy import select as _sel, update as _upd, and_ as _and, or_ as _or
    from app.db.models import Keyword as _Keyword, Qoo10Product as _Q, DomesticProduct as _DP
    from app.services.llm.category import classify_category_async
    from app.services.llm.brand import is_brand_keyword_async

    task_manager.start_task(task_id)
    processed = 0
    failed = 0

    try:
        # 1) 대상 행 수집 (category_inferred 가 비어있는 것만 — brand 도 같이 채움)
        async with async_session() as session:
            stmt = _sel(_Keyword.id, _Keyword.keyword_jp, _Keyword.keyword_kr).where(
                _and(
                    _Keyword.lookup_date == target_date,
                    _or(_Keyword.category_inferred.is_(None), _Keyword.category_inferred == ""),
                )
            )
            rows = (await session.execute(stmt)).all()

        # 2) (keyword_kr or keyword_jp) → row_ids + jp/kr 매핑 (examples 조회용)
        text_to_ids: dict[str, list[int]] = {}
        text_to_jp: dict[str, str] = {}
        text_to_kr: dict[str, str] = {}
        for row in rows:
            kid, kw_jp, kw_kr = row
            text = (kw_kr or kw_jp or "").strip()
            if not text:
                continue
            text_to_ids.setdefault(text, []).append(kid)
            if kw_jp and text not in text_to_jp:
                text_to_jp[text] = kw_jp
            if kw_kr and text not in text_to_kr:
                text_to_kr[text] = kw_kr

        unique_texts = list(text_to_ids.keys())
        if limit:
            unique_texts = unique_texts[:limit]

        # 2-b) 각 키워드의 큐텐(jp) / 한국(kr) 상품명 5개 examples 한 번에 모음
        # 같은 search_keyword 의 어떤 lookup_date 든 OK — 가장 최근 5개.
        examples_map: dict[str, list[str]] = {}
        if unique_texts:
            async with async_session() as session:
                jps = sorted({text_to_jp.get(t, "") for t in unique_texts if text_to_jp.get(t)})
                krs = sorted({text_to_kr.get(t, "") for t in unique_texts if text_to_kr.get(t)})
                if jps:
                    q_rows = (await session.execute(
                        _sel(_Q.search_keyword, _Q.product_name)
                        .where(_Q.search_keyword.in_(jps))
                        .where(_Q.product_name.is_not(None))
                        .order_by(_Q.lookup_date.desc(), _Q.id.desc())
                    )).all()
                    for kw, pn in q_rows:
                        if not kw or not pn:
                            continue
                        # 키워드 텍스트는 kr 우선 매핑이라 jp 로 들어왔어도 text 로 변환
                        for t in unique_texts:
                            if text_to_jp.get(t) == kw and len(examples_map.setdefault(t, [])) < 5:
                                examples_map[t].append(pn)
                if krs:
                    d_rows = (await session.execute(
                        _sel(_DP.search_keyword, _DP.product_name)
                        .where(_DP.search_keyword.in_(krs))
                        .where(_DP.product_name.is_not(None))
                        .order_by(_DP.lookup_date.desc(), _DP.id.desc())
                    )).all()
                    for kw, pn in d_rows:
                        if not kw or not pn:
                            continue
                        for t in unique_texts:
                            if text_to_kr.get(t) == kw and len(examples_map.setdefault(t, [])) < 5:
                                examples_map[t].append(pn)

        # 3) 순차 분류 + UPDATE (카테고리 + 브랜드 둘 다)
        for idx, text in enumerate(unique_texts, 1):
            label = "기타"
            brand_info = {
                "is_brand": False, "brand_kr": "", "brand_jp": "", "brand_en": "",
            }
            try:
                label = await classify_category_async(text, examples=examples_map.get(text))
            except Exception:
                failed += 1
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(unique_texts)}] 카테고리 실패: {text[:30]}",
                )
                continue

            try:
                brand_info = await is_brand_keyword_async(text)
            except Exception:
                pass  # 브랜드 판별 실패해도 카테고리만이라도 저장

            ids = text_to_ids[text]
            try:
                async with async_session() as session:
                    await session.execute(
                        _upd(_Keyword)
                        .where(_Keyword.id.in_(ids))
                        .values(
                            category_inferred=label,
                            is_brand=1 if brand_info.get("is_brand") else 0,
                            brand_kr=(brand_info.get("brand_kr") or "")[:200],
                            brand_jp=(brand_info.get("brand_jp") or "")[:200],
                            brand_en=(brand_info.get("brand_en") or "")[:200],
                        )
                    )
                    await session.commit()
                processed += 1
            except Exception:
                failed += 1
            finally:
                brand_tag = f" ★{brand_info.get('brand_kr')}" if brand_info.get("is_brand") else ""
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(unique_texts)}] {text[:20]} → {label}{brand_tag}",
                )

        task_manager.complete_task(
            task_id,
            message=f"완료 — 분류 {processed}, 실패 {failed} (unique {len(unique_texts)})",
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()


@router.post("/retranslate")
async def retranslate_keywords(only_missing: bool = False):
    """기존 DB 키워드의 keyword_kr을 구글 번역으로 일괄 재번역.

    only_missing=True: 한국어가 없는 것만
    only_missing=False: 전체 재번역
    """
    from sqlalchemy import select, update
    from app.db.models import Keyword

    # 1) 대상 수집
    async with async_session() as session:
        stmt = select(Keyword.keyword_jp, Keyword.keyword_kr).distinct()
        result = await session.execute(stmt)
        pairs = result.all()

    targets_jp = []
    seen = set()
    for jp, kr in pairs:
        if not jp or jp in seen:
            continue
        seen.add(jp)
        if only_missing and kr:
            continue
        targets_jp.append(jp)

    if not targets_jp:
        return {"status": "empty", "total": 0}

    # 2) 태스크 생성
    task_id = task_manager.create_task(
        f"키워드 재번역 ({len(targets_jp)}개)", len(targets_jp)
    )
    task_manager.start_task(task_id)

    async def _run():
        try:
            # 청크 단위로 번역 (한번에 너무 많으면 오래 걸림)
            chunk = 50
            updates: dict[str, str] = {}
            for i in range(0, len(targets_jp), chunk):
                batch = targets_jp[i:i + chunk]
                translations = await translate_batch(batch, source="ja", target="ko", concurrency=5)
                for jp, ko in zip(batch, translations):
                    if ko and ko != jp:
                        updates[jp] = ko
                task_manager.update_progress(
                    task_id, len(batch), f"{i + len(batch)}/{len(targets_jp)} 번역 완료"
                )

            # 3) DB 일괄 업데이트
            async with async_session() as session:
                for jp, ko in updates.items():
                    await session.execute(
                        update(Keyword).where(Keyword.keyword_jp == jp).values(keyword_kr=ko)
                    )
                await session.commit()

            task_manager.complete_task(task_id, f"{len(updates)}개 키워드 재번역 완료")
        except Exception as e:
            traceback.print_exc()
            task_manager.fail_task(task_id, f"실패: {e}")

    asyncio.create_task(_run())
    return {"status": "started", "task_id": task_id, "total": len(targets_jp)}


@router.delete("/by-date/{lookup_date}")
async def delete_by_date(lookup_date: date, session: AsyncSession = Depends(get_session)):
    repo = SQLiteKeywordRepository(session)
    deleted = await repo.delete_by_date(lookup_date)
    return {"status": "deleted", "count": deleted, "lookup_date": str(lookup_date)}


async def _get_product_counts(page, keyword_jp: str) -> dict:
    """큐텐 검색 페이지에서 전체/JP/KR/CN/OT 상품수 추출.
    VBA: #items strong (전체), #div_global_domestic_tab .tab .local[data-nation_code] + .num
    """
    out = {"total_products": 0, "products_jp": 0, "products_kr": 0, "products_cn": 0, "products_other": 0}
    try:
        url = f"{settings.QOO10_SEARCH_URL}?keyword={keyword_jp}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1200)

        # 전체 상품수
        for sel in ["#items strong", ".search-count strong", ".result_total strong"]:
            el = await page.query_selector(sel)
            if el:
                text = await el.inner_text()
                nums = re.sub(r"[^\d]", "", text)
                if nums:
                    out["total_products"] = int(nums)
                    break

        # 국가별 상품수 (#div_global_domestic_tab .tab .local[data-nation_code])
        tabs = await page.query_selector_all("#div_global_domestic_tab .tab")
        for tab in tabs:
            local = await tab.query_selector(".local[data-nation_code]")
            if not local:
                continue
            nation = (await local.get_attribute("data-nation_code")) or ""
            num_el = await tab.query_selector(".num")
            if not num_el:
                continue
            num_text = (await num_el.inner_text()).strip()  # "(56,843)"
            digits = re.sub(r"[^\d]", "", num_text)
            n = int(digits) if digits else 0
            if nation == "JP":
                out["products_jp"] = n
            elif nation == "KR":
                out["products_kr"] = n
            elif nation == "CN":
                out["products_cn"] = n
            elif nation == "OT":
                out["products_other"] = n
    except Exception:
        pass
    return out


def _resolve_categories(req: TrendKeywordRequest) -> list[int]:
    if req.categories:
        if 0 in req.categories or not req.categories:
            return list(CATEGORIES.keys())
        return [c for c in req.categories if c in CATEGORIES]
    if req.category is None or req.category == 0:
        return list(CATEGORIES.keys())
    return [req.category]


@router.post("/trend")
async def collect_trend_keywords(req: TrendKeywordRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    target_categories = _resolve_categories(req)

    # 전체 진척도 (마스터) task: 카테고리 N개 + 번역 1 + 상품수 1 + 저장 1 (+ 비딩 1)
    total_steps = (
        len(target_categories)
        + (1 if req.translate else 0)
        + (1 if req.fill_total_products else 0)
        + 1
        + (1 if req.collect_bids else 0)
    )
    master_id = task_manager.create_task(
        f"키워드 수집 ({len(target_categories)}개 카테고리)", total_steps
    )
    task_manager.start_task(master_id)

    async def _task():
        try:
            scraper = TrendKeywordScraper(browser_manager, task_manager)
            all_keywords: list[dict] = []

            for i, cat in enumerate(target_categories, 1):
                cat_name = CATEGORIES.get(cat, str(cat))
                task_manager.update_progress(master_id, 0, f"카테고리 수집 중: {cat_name} ({i}/{len(target_categories)})")
                result = await scraper.run(category=cat, types=["popular", "daily", "weekly"])
                kws = result.get("keywords") or []
                all_keywords.extend(kws)
                print(f"[trend] category={cat} 수집 {len(kws)}개 (누계 {len(all_keywords)})")
                task_manager.update_progress(master_id, 1, f"{cat_name} 완료 ({i}/{len(target_categories)}, 누계 {len(all_keywords)}개)")

            if not all_keywords:
                task_manager.fail_task(master_id, "수집된 키워드 없음")
                return {"error": "수집된 키워드 없음"}

            # 오늘 날짜로 강제 (일자별 적재)
            today = date.today()
            for kw in all_keywords:
                kw["lookup_date"] = today

            # 1) 한국어 번역 (중복 제거 후 batch)
            if req.translate:
                unique_jp = list({kw["keyword_jp"] for kw in all_keywords if kw.get("keyword_jp")})
                task_manager.update_progress(master_id, 0, f"한국어 번역 중 ({len(unique_jp)}개)")
                print(f"[trend] 번역 {len(unique_jp)}개")
                translations = await translate_batch(unique_jp, source="ja", target="ko")
                tr_map = dict(zip(unique_jp, translations))
                for kw in all_keywords:
                    kw["keyword_kr"] = tr_map.get(kw["keyword_jp"], "")
                task_manager.update_progress(master_id, 1, f"번역 완료 ({len(unique_jp)}개)")

            # 2) 전체/국가별 상품수 채우기 (큐텐 검색 페이지)
            if req.fill_total_products:
                page = await browser_manager.get_page()
                unique_jp = list({kw["keyword_jp"] for kw in all_keywords if kw.get("keyword_jp")})
                cnt_map: dict[str, dict] = {}
                tid = task_manager.create_task("상품수 수집 (전체/국가별)", len(unique_jp))
                task_manager.start_task(tid)
                for i, jp in enumerate(unique_jp, 1):
                    counts = await _get_product_counts(page, jp)
                    cnt_map[jp] = counts
                    task_manager.update_progress(
                        tid, 1,
                        f"{jp}: 전체 {counts['total_products']:,} / JP {counts['products_jp']:,} / KR {counts['products_kr']:,} ({i}/{len(unique_jp)})"
                    )
                task_manager.complete_task(tid, f"{len(unique_jp)}개 키워드 상품수 수집 완료")
                task_manager.update_progress(master_id, 1, f"상품수 수집 완료 ({len(unique_jp)}개)")
                for kw in all_keywords:
                    counts = cnt_map.get(kw["keyword_jp"], {})
                    kw["total_products"] = counts.get("total_products", 0)
                    kw["products_jp"] = counts.get("products_jp", 0)
                    kw["products_kr"] = counts.get("products_kr", 0)
                    kw["products_cn"] = counts.get("products_cn", 0)
                    kw["products_other"] = counts.get("products_other", 0)
                    # 경쟁강도 계산 (전체상품수 / 주평검색수)
                    sw = kw.get("search_volume_weekly") or 0
                    if sw > 0 and kw["total_products"] > 0:
                        kw["competition_intensity"] = round(kw["total_products"] / sw, 2)

            # DB 저장
            task_manager.update_progress(master_id, 0, "DB 저장 중...")
            async with async_session() as session:
                repo = SQLiteKeywordRepository(session)
                await repo.save_keywords(all_keywords)
            task_manager.update_progress(master_id, 1, f"DB 저장 완료 ({len(all_keywords)}개)")

            # 경매 낙찰 결과 수집 — 옵션 (collect_bids=True일 때만)
            if req.collect_bids:
                try:
                    unique_jp = list({kw["keyword_jp"] for kw in all_keywords if kw.get("keyword_jp")})
                    if unique_jp:
                        task_manager.update_progress(master_id, 0, f"경매 낙찰가 수집 중 ({len(unique_jp)}개)")
                        bid_scraper = BidResultScraper(browser_manager, task_manager)
                        bid_result = await bid_scraper.run(keywords=unique_jp)
                        bid_records = bid_result.get("results") or []
                        if bid_records:
                            async with async_session() as session:
                                bid_repo = SQLiteBidRepository(session)
                                await bid_repo.replace_bid_history(today, bid_records)
                            print(f"[trend] 경매결과 {len(bid_records)}개 저장")
                        task_manager.update_progress(master_id, 1, f"경매 낙찰가 수집 완료 ({len(bid_records)}개)")
                except Exception as be:
                    # 경매 수집 실패해도 키워드 수집 자체는 성공으로 처리
                    print(f"[trend] 경매결과 수집 실패(무시): {be}")
                    traceback.print_exc()
                    task_manager.update_progress(master_id, 1, f"경매 낙찰가 수집 실패: {be}")

            task_manager.complete_task(master_id, f"{len(all_keywords)}개 키워드 적재 완료")

            return {"status": "ok", "saved": len(all_keywords)}
        except Exception as e:
            traceback.print_exc()
            task_manager.fail_task(master_id, str(e))
            return {"error": str(e)}

    asyncio.create_task(_task())
    cat_names = ", ".join(CATEGORIES[c] for c in target_categories)
    return {
        "status": "started",
        "message": f"{len(target_categories)}개 카테고리 수집 시작: {cat_names}",
        "categories": target_categories,
        "master_task_id": master_id,
    }


@router.post("/related")
async def collect_related_keywords(req: RelatedKeywordRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    async def _task():
        try:
            scraper = RelatedKeywordScraper(browser_manager, task_manager)
            result = await scraper.run(keywords=req.keywords)

            if "keywords" in result and result["keywords"]:
                today = date.today()
                for kw in result["keywords"]:
                    kw["lookup_date"] = today
                async with async_session() as session:
                    repo = SQLiteKeywordRepository(session)
                    await repo.save_keywords(result["keywords"])

            return result
        except Exception as e:
            traceback.print_exc()
            return {"error": str(e)}

    asyncio.create_task(_task())
    return {"status": "started", "message": "연관 키워드 수집을 시작합니다."}


# ─── Phase 1-D — 브랜드 키워드 확장 ─────────────────────


@router.post("/expand-brand")
async def expand_brand_endpoint(body: dict | None = None):
    """is_brand=1 키워드의 큐텐 상위 N개 상품명에서 specific 키워드 LLM 추출 (백그라운드).

    body:
      date:       YYYY-MM-DD (4/27 형식 — keywords lookup_date)
      qoo10_date: YYYY-MM-DD (큐텐 상품 lookup_date — 기본 = date)
      top_n:      int (큐텐 상위 N개 상품명, 기본 10)
      limit:      int (처리할 brand 키워드 상한)
      brands:     list[str] (선택, 특정 brand_kr 만)
    """
    import asyncio as _asyncio
    from datetime import date as _date_cls, datetime as _dt
    from sqlalchemy import select as _sel, func as _func
    from app.db.models import Keyword as _K, Qoo10Product as _Q

    body = body or {}
    raw_date = body.get("date")
    if raw_date:
        try:
            target_date = _dt.strptime(str(raw_date), "%Y-%m-%d").date()
        except ValueError:
            return {"error": "date 형식: YYYY-MM-DD"}
    else:
        target_date = _date_cls.today()

    raw_qd = body.get("qoo10_date")
    if raw_qd:
        try:
            qoo10_date = _dt.strptime(str(raw_qd), "%Y-%m-%d").date()
        except ValueError:
            return {"error": "qoo10_date 형식: YYYY-MM-DD"}
    else:
        qoo10_date = target_date

    top_n = int(body.get("top_n", 10))
    raw_limit = body.get("limit")
    limit = int(raw_limit) if raw_limit else None
    brands_filter = body.get("brands") or []

    # is_brand=1 키워드 추출
    async with async_session() as session:
        stmt = (
            _sel(_K.keyword_jp, _K.brand_kr, _K.search_volume_daily)
            .where(_K.lookup_date == target_date)
            .where(_K.is_brand == 1)
            .where(_K.keyword_jp.is_not(None))
            .order_by(_K.search_volume_daily.desc().nullslast())
        )
        if brands_filter:
            stmt = stmt.where(_K.brand_kr.in_(brands_filter))
        rows = (await session.execute(stmt)).all()
        # unique by keyword_jp
        seen = set()
        unique_rows = []
        for jp, br, vol in rows:
            if jp in seen:
                continue
            seen.add(jp)
            unique_rows.append((jp, br or "", vol or 0))

    if limit:
        unique_rows = unique_rows[:limit]

    if not unique_rows:
        return {
            "task_id": None, "candidates": 0,
            "message": f"{target_date}: is_brand=1 키워드 0건",
        }

    task_id = task_manager.create_task(
        name=f"브랜드 키워드 확장 ({target_date}, {len(unique_rows)}개)",
        total=len(unique_rows),
    )
    _asyncio.create_task(_run_expand_brand(task_id, unique_rows, qoo10_date, top_n))
    return {
        "task_id": task_id, "candidates": len(unique_rows),
        "qoo10_date": str(qoo10_date), "top_n": top_n,
        "date": str(target_date),
    }


async def _run_expand_brand(task_id: str, rows: list, qoo10_date, top_n: int) -> None:
    """백그라운드 — 각 브랜드 키워드의 큐텐 상위 N개 상품명 → LLM expand → DB INSERT."""
    from sqlalchemy import select as _sel
    from sqlalchemy.exc import IntegrityError
    from app.db.models import Qoo10Product as _Q, ExpandedKeyword as _EK
    from app.services.llm.brand_expand import expand_brand_keyword_async

    task_manager.start_task(task_id)
    expanded_n = empty_n = 0

    try:
        for idx, (brand_jp, brand_kr, vol) in enumerate(rows, 1):
            # 큐텐 상위 N개 상품명 (search_keyword == brand_jp 매칭)
            async with async_session() as db:
                p_rows = (await db.execute(
                    _sel(_Q.product_name)
                    .where(_Q.search_keyword == brand_jp)
                    .where(_Q.lookup_date == qoo10_date)
                    .where(_Q.product_name.is_not(None))
                    .order_by(_Q.id.asc())
                    .limit(top_n)
                )).all()
            product_names = [r[0] for r in p_rows if r[0]]

            if not product_names:
                empty_n += 1
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(rows)}] SKIP {brand_jp[:25]} (큐텐 상품 0)",
                )
                continue

            try:
                expansions = await expand_brand_keyword_async(
                    brand_jp=brand_jp,
                    brand_kr=brand_kr,
                    product_names=product_names,
                )
            except Exception as e:
                logger.warning(f"[brand_expand] LLM 실패 {brand_jp!r}: {e}")
                expansions = []

            if not expansions:
                empty_n += 1
                task_manager.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(rows)}] EMPTY {brand_jp[:25]} (LLM 추출 0)",
                )
                continue

            # DB INSERT (중복 (parent_jp, keyword_jp) 회피)
            inserted = 0
            try:
                async with async_session() as db:
                    # 같은 parent_jp 의 기존 keyword_jp 제외
                    existing = (await db.execute(
                        _sel(_EK.keyword_jp).where(_EK.parent_jp == brand_jp)
                    )).all()
                    existing_set = {r[0] for r in existing}
                    for exp in expansions:
                        kw = exp.get("keyword_jp")
                        if not kw or kw in existing_set:
                            continue
                        db.add(_EK(
                            parent_jp=brand_jp,
                            parent_kr=brand_kr or None,
                            keyword_jp=kw,
                            keyword_kr=exp.get("keyword_kr") or None,
                            source_count=len(product_names),
                        ))
                        inserted += 1
                    await db.commit()
            except Exception as e:
                logger.warning(f"[brand_expand] DB INSERT 실패 {brand_jp!r}: {e}")

            expanded_n += inserted
            kws_preview = ", ".join(e["keyword_jp"][:20] for e in expansions[:3])
            task_manager.update_progress(
                task_id, increment=1,
                message=(
                    f"[{idx}/{len(rows)}] OK {brand_jp[:18]} "
                    f"+{inserted}/{len(expansions)} → [{kws_preview}]"
                ),
            )

        task_manager.complete_task(
            task_id,
            message=f"완료 — 확장 {expanded_n}개, 빈 {empty_n} (대상 brand {len(rows)})",
        )
    except Exception as e:
        task_manager.fail_task(task_id, message=f"실패: {type(e).__name__}: {e}")
        traceback.print_exc()
