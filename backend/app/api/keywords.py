import asyncio
import re
import traceback
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.config import settings
from app.db.connection import get_session, async_session
from app.db.sqlite_repo import SQLiteKeywordRepository
from app.schemas.keyword import TrendKeywordRequest, RelatedKeywordRequest
from app.scrapers.m02_trend_keywords import TrendKeywordScraper, CATEGORIES
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

    # 전체 진척도 (마스터) task: 카테고리 N개 + 번역 1 + 상품수 1 + 저장 1
    total_steps = len(target_categories) + (1 if req.translate else 0) + (1 if req.fill_total_products else 0) + 1
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
