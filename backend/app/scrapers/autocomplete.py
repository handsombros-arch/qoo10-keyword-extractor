"""자동완성/연관 키워드 수집 (큐텐, 야후재팬 쇼핑) — 모두 브라우저 기반."""
from datetime import date
from typing import List, Dict


async def _flexible_suggest(page, input_selectors: list[str], suggest_selectors: list[str], keyword: str) -> List[str]:
    """검색창에 타이핑 후 자동완성 항목을 다양한 셀렉터로 시도."""
    box = None
    for sel in input_selectors:
        box = await page.query_selector(sel)
        if box:
            break
    if not box:
        return []
    try:
        await box.click()
        await box.fill("")
        await box.type(keyword, delay=60)
        await page.wait_for_timeout(1500)
    except Exception:
        return []

    results: List[str] = []
    for sel in suggest_selectors:
        try:
            items = await page.query_selector_all(sel)
            for it in items:
                t = (await it.inner_text()).strip()
                t = t.splitlines()[0].strip() if t else t
                if t and t != keyword and len(t) < 80 and t not in results:
                    results.append(t)
            if results:
                return results[:30]
        except Exception:
            continue
    return results[:30]


async def qoo10_autocomplete(page, keyword: str) -> List[str]:
    """큐텐 검색창에 타이핑 → 자동완성 추출."""
    try:
        await page.goto("https://www.qoo10.jp/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(800)
    except Exception:
        return []
    return await _flexible_suggest(
        page,
        input_selectors=[
            "#keyword",
            "input[name='keyword']",
            "input[type='search']",
            "#search_keyword",
            ".gnb_search input",
        ],
        suggest_selectors=[
            # 2026-06 현재 큐텐 DOM (셀렉터 갱신 — 읽기전용 테스트로 31개 추출 검증)
            "[class*='auto'] li a",
            "[class*='auto'] li",
            # 레거시 폴백
            "#auto_keyword li a",
            "#auto_keyword li",
            ".auto_keyword li",
            ".ui-autocomplete li",
            "[role='listbox'] [role='option']",
            ".autoCmpl_list li",
            ".search_auto li",
        ],
        keyword=keyword,
    )


async def yahoo_shopping_autocomplete(page, keyword: str) -> List[str]:
    """야후재팬 쇼핑 검색창 자동완성 (브라우저 기반)."""
    try:
        await page.goto("https://shopping.yahoo.co.jp/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(800)
    except Exception:
        return []
    return await _flexible_suggest(
        page,
        input_selectors=[
            "input[name='p']",
            "input[type='search']",
            "#srchtxt",
            ".SearchBox__input",
        ],
        suggest_selectors=[
            "[class*='Suggest'] li",
            "[class*='suggest'] li",
            ".ui-autocomplete li",
            "[role='listbox'] [role='option']",
            "ul[role='listbox'] li",
        ],
        keyword=keyword,
    )


async def yahoo_shopping_related(page, keyword: str) -> List[str]:
    """야후재팬 쇼핑 검색 결과 페이지의 관련 키워드 섹션."""
    try:
        url = f"https://search.shopping.yahoo.co.jp/search?p={keyword}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
    except Exception:
        return []

    results: List[str] = []
    for sel in [
        "[class*='RelatedKeyword'] a",
        "[class*='relatedKeyword'] a",
        "[class*='Related'] a",
        "a[data-action*='related']",
        # 키워드 드릴다운 링크들
        "nav a[href*='/search?p=']",
    ]:
        try:
            items = await page.query_selector_all(sel)
            for it in items:
                t = (await it.inner_text()).strip()
                t = t.splitlines()[0].strip() if t else t
                if t and t != keyword and 1 <= len(t) <= 40 and t not in results:
                    results.append(t)
            if len(results) > 15:
                break
        except Exception:
            continue
    return results[:30]


def make_keyword_dict(keyword_jp: str, source: str) -> Dict:
    """공통 키워드 딕셔너리."""
    cls = {
        "qoo10_related": "연관",
        "qoo10_similar": "유사",
        "qoo10_ad_related": "광고연관",
        "qoo10_autocomplete": "자동완성",
        "yahoo_shopping_autocomplete": "야후쇼핑자동",
        "yahoo_shopping_related": "야후쇼핑연관",
    }.get(source, source)
    return {
        "keyword_jp": keyword_jp,
        "lookup_date": date.today(),
        "classification": cls,
        "index_key": f"{date.today()}_{cls}_{keyword_jp}",
    }
