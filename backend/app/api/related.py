"""연관 키워드 일괄 수집 API."""
import asyncio
import traceback
from datetime import date
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

from app.browser.manager import browser_manager
from app.db.connection import async_session
from app.db.sqlite_repo import SQLiteKeywordRepository
from app.scrapers.autocomplete import (
    qoo10_autocomplete,
    amazon_autocomplete,
    amazon_related,
    yahoo_autocomplete,
    yahoo_related,
    yahoo_shopping_autocomplete,
    yahoo_shopping_related,
    make_keyword_dict,
)
from app.scrapers.m05_related_keywords import RelatedKeywordScraper
from app.services.task_manager import task_manager
from app.services.translation import translate_papago

router = APIRouter(prefix="/api/related", tags=["related"])


class RelatedRequest(BaseModel):
    keywords_ja: List[str] = []
    keywords_ko: List[str] = []
    # 플랫폼
    qoo10_ad_related: bool = True      # 큐텐 키워드광고 연관 (M05의 "유사")
    qoo10_autocomplete: bool = True    # 큐텐 자동완성
    qoo10_related: bool = True         # 큐텐 연관 (M05의 "연관")
    amazon_autocomplete: bool = True   # 아마존재팬 자동완성 (#nav-flyout-searchAjax)
    amazon_related: bool = True        # 아마존재팬 관련검색
    yahoo_autocomplete: bool = True    # 야후재팬(웹) 자동완성 (search.yahoo.co.jp #assist)
    yahoo_related: bool = True         # 야후재팬(웹) 관련검색 (.Contents__innerGroupFooter)
    yahoo_shopping_autocomplete: bool = True
    yahoo_shopping_related: bool = True
    # 추가기능
    remove_zero_search: bool = False
    run_competition: bool = False
    run_bid: bool = False


@router.post("/collect")
async def collect_related(req: RelatedRequest):
    if not browser_manager.is_logged_in:
        return {"error": "QSM 로그인이 필요합니다."}

    # 1) 입력 키워드 정규화: 엔터/콤마로 나누기, 한글도 일본어 번역
    def _split(raw_list: list[str]) -> list[str]:
        out = []
        for s in raw_list:
            for p in str(s).replace(",", "\n").split("\n"):
                p = p.strip()
                if p:
                    out.append(p)
        return out

    jp_list = _split(req.keywords_ja)[:20]
    ko_list = _split(req.keywords_ko)[:20]

    # 한글 → 일본어 번역
    if ko_list:
        translations = await asyncio.gather(*[translate_papago(k, "ko", "ja") for k in ko_list])
        for t in translations:
            if t and t not in jp_list:
                jp_list.append(t)

    if not jp_list:
        return {"error": "키워드가 비어 있습니다."}

    total_steps = len(jp_list) * sum([
        req.qoo10_ad_related or req.qoo10_related, req.qoo10_autocomplete,
        req.amazon_autocomplete, req.amazon_related,
        req.yahoo_autocomplete, req.yahoo_related,
        req.yahoo_shopping_autocomplete, req.yahoo_shopping_related,
    ])
    master_id = task_manager.create_task(f"연관 키워드 수집 ({len(jp_list)}개)", max(1, total_steps))
    task_manager.start_task(master_id)

    async def _task():
        try:
            all_results: list[dict] = []

            # Qoo10 연관/유사 (M05 재사용) — 둘 다 같이 수집되므로 한 번에
            if req.qoo10_ad_related or req.qoo10_related:
                scraper = RelatedKeywordScraper(browser_manager, task_manager)
                result = await scraper.run(keywords=jp_list)
                kws = result.get("keywords") or []
                # classification 필터
                for kw in kws:
                    cls = kw.get("classification")
                    if cls == "유사" and not req.qoo10_ad_related:
                        continue
                    if cls == "연관" and not req.qoo10_related:
                        continue
                    all_results.append(kw)
                task_manager.update_progress(master_id, len(jp_list), f"큐텐 연관/유사 완료: {len(kws)}개")

            page = None
            if (req.qoo10_autocomplete or req.amazon_autocomplete or req.amazon_related
                    or req.yahoo_autocomplete or req.yahoo_related
                    or req.yahoo_shopping_autocomplete or req.yahoo_shopping_related):
                page = await browser_manager.get_page()

            if req.qoo10_autocomplete and page:
                for kw in jp_list:
                    try:
                        suggests = await qoo10_autocomplete(page, kw)
                        print(f"[qoo10_autocomplete] {kw}: {len(suggests)}개")
                        for s in suggests:
                            all_results.append(make_keyword_dict(s, "qoo10_autocomplete"))
                    except Exception as e:
                        print(f"[qoo10_autocomplete] {kw} ERROR: {e}")
                    task_manager.update_progress(master_id, 1, f"큐텐 자동완성 '{kw}' 완료")

            if req.amazon_autocomplete and page:
                for kw in jp_list:
                    try:
                        suggests = await amazon_autocomplete(page, kw)
                        print(f"[amazon_autocomplete] {kw}: {len(suggests)}개")
                        for s in suggests:
                            if s:
                                all_results.append(make_keyword_dict(s, "amazon_autocomplete"))
                    except Exception as e:
                        print(f"[amazon_autocomplete] {kw} ERROR: {e}")
                    task_manager.update_progress(master_id, 1, f"아마존 자동완성 '{kw}' 완료")

            if req.amazon_related and page:
                for kw in jp_list:
                    try:
                        rel = await amazon_related(page, kw)
                        print(f"[amazon_related] {kw}: {len(rel)}개")
                        for r in rel:
                            if r:
                                all_results.append(make_keyword_dict(r, "amazon_related"))
                    except Exception as e:
                        print(f"[amazon_related] {kw} ERROR: {e}")
                    task_manager.update_progress(master_id, 1, f"아마존 연관 '{kw}' 완료")

            if req.yahoo_autocomplete and page:
                for kw in jp_list:
                    try:
                        suggests = await yahoo_autocomplete(page, kw)
                        print(f"[yahoo_autocomplete] {kw}: {len(suggests)}개")
                        for s in suggests:
                            if s:
                                all_results.append(make_keyword_dict(s, "yahoo_autocomplete"))
                    except Exception as e:
                        print(f"[yahoo_autocomplete] {kw} ERROR: {e}")
                    task_manager.update_progress(master_id, 1, f"야후웹 자동완성 '{kw}' 완료")

            if req.yahoo_related and page:
                for kw in jp_list:
                    try:
                        rel = await yahoo_related(page, kw)
                        print(f"[yahoo_related] {kw}: {len(rel)}개")
                        for r in rel:
                            if r:
                                all_results.append(make_keyword_dict(r, "yahoo_related"))
                    except Exception as e:
                        print(f"[yahoo_related] {kw} ERROR: {e}")
                    task_manager.update_progress(master_id, 1, f"야후웹 연관 '{kw}' 완료")

            if req.yahoo_shopping_autocomplete and page:
                for kw in jp_list:
                    try:
                        suggests = await yahoo_shopping_autocomplete(page, kw)
                        print(f"[yahoo_shopping_auto] {kw}: {len(suggests)}개")
                        for s in suggests:
                            if s:
                                all_results.append(make_keyword_dict(s, "yahoo_shopping_autocomplete"))
                    except Exception as e:
                        print(f"[yahoo_shopping_auto] {kw} ERROR: {e}")
                    task_manager.update_progress(master_id, 1, f"야후쇼핑 자동완성 '{kw}' 완료")

            if req.yahoo_shopping_related and page:
                for kw in jp_list:
                    try:
                        rel = await yahoo_shopping_related(page, kw)
                        print(f"[yahoo_shopping_related] {kw}: {len(rel)}개")
                        for r in rel:
                            all_results.append(make_keyword_dict(r, "yahoo_shopping_related"))
                    except Exception as e:
                        print(f"[yahoo_shopping_related] {kw} ERROR: {e}")
                    task_manager.update_progress(master_id, 1, f"야후쇼핑 연관 '{kw}' 완료")

            # 중복 제거: (keyword_jp, classification) 기준
            seen = set()
            deduped = []
            for kw in all_results:
                k = (kw.get("keyword_jp"), kw.get("classification"))
                if k in seen:
                    continue
                seen.add(k)
                deduped.append(kw)
            all_results = deduped

            # 검색수 0 제거 옵션
            if req.remove_zero_search:
                all_results = [
                    kw for kw in all_results
                    if (kw.get("search_volume_weekly") or 0) > 0
                    or (kw.get("search_volume_daily") or 0) > 0
                    or kw.get("classification") in ("자동완성", "아마존자동", "아마존연관", "야후자동", "야후연관", "야후쇼핑자동", "야후쇼핑연관")
                    # 검색량 정보 없는 소스는 그대로 유지 (0 판정 불가)
                ]

            # DB 저장
            async with async_session() as session:
                repo = SQLiteKeywordRepository(session)
                await repo.save_keywords(all_results)

            task_manager.complete_task(master_id, f"연관 키워드 {len(all_results)}개 적재 완료")
            return {"saved": len(all_results)}
        except Exception as e:
            traceback.print_exc()
            task_manager.fail_task(master_id, str(e))
            return {"error": str(e)}

    asyncio.create_task(_task())
    return {
        "status": "started",
        "master_task_id": master_id,
        "keywords_jp": jp_list,
        "message": f"{len(jp_list)}개 키워드에 대해 연관 수집 시작",
    }
