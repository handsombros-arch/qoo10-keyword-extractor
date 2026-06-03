"""자동완성/연관 키워드 수집 (큐텐, 아마존JP, 야후재팬/쇼핑, 구글).

대부분 브라우저(page) 기반이나 google_suggest 만 httpx(브라우저 불필요).
"""
from datetime import date
from typing import List, Dict

import httpx


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
    """야후재팬 쇼핑 관련검색어 — 원본 방식: shopping.yahoo.co.jp/search?p= + #rel_mid1 li.

    (기존 search.shopping.yahoo + RelatedKeyword 셀렉터는 DOM 변경으로 0개였음 — 원본 방식으로 교체)
    """
    try:
        await page.goto(f"https://shopping.yahoo.co.jp/search?p={keyword}",
                        wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1800)
    except Exception:
        return []
    return await _collect_items(page, ["#rel_mid1 li", "[id*='rel_mid'] li"], keyword)


async def yahoo_autocomplete(page, keyword: str) -> List[str]:
    """야후재팬(웹, 쇼핑 아님) 자동완성 — 원본 VBA 방식 재현.

    톱페이지가 아니라 검색결과 페이지(search.yahoo.co.jp/search?p=)로 진입해
    키워드가 채워진 검색창(.SearchBox__searchInputWrap)을 클릭하면 #assist 에
    자동완성이 뜬다. (2026-06 읽기전용 테스트로 검증)
    """
    try:
        await page.goto(
            f"https://search.yahoo.co.jp/search?p={keyword}",
            wait_until="domcontentloaded", timeout=30000,
        )
        await page.wait_for_timeout(1000)
    except Exception:
        return []

    # 검색창 클릭 → assist 드롭다운 열기
    for sel in [".SearchBox__searchInputWrap", "input[name='p']", "[class*='SearchBox'] input"]:
        el = await page.query_selector(sel)
        if el:
            try:
                await el.click()
                break
            except Exception:
                continue
    await page.wait_for_timeout(1200)

    # assist 항목 추출 + UI/광고 노이즈 제거
    NOISE = ("設定", "Agent", "聞いて", "検索履歴")
    results: List[str] = []
    for sel in ["#assist li", "[class*='assist'] li"]:
        try:
            items = await page.query_selector_all(sel)
            for it in items:
                t = (await it.inner_text()).strip()
                t = t.splitlines()[0].strip() if t else t
                if not t or t == keyword or len(t) >= 80:
                    continue
                if any(n in t for n in NOISE) or t.endswith("へ"):
                    continue
                if t not in results:
                    results.append(t)
            if results:
                return results[:30]
        except Exception:
            continue
    return results[:30]


NOISE_GENERIC = ("設定", "Agent", "聞いて", "検索履歴")


async def _collect_items(page, selectors: list, keyword: str, noise: tuple = NOISE_GENERIC) -> List[str]:
    """여러 셀렉터로 li/a 텍스트 수집 + UI/광고/질문형 노이즈 제거 (원본 공통 패턴)."""
    results: List[str] = []
    for sel in selectors:
        try:
            items = await page.query_selector_all(sel)
            for it in items:
                t = (await it.inner_text()).strip()
                t = t.splitlines()[0].strip() if t else t
                if not t or t == keyword or len(t) >= 80:
                    continue
                if any(n in t for n in noise) or t.endswith("？") or t.endswith("?") or t.endswith("へ"):
                    continue
                if t not in results:
                    results.append(t)
            if results:
                return results[:30]
        except Exception:
            continue
    return results[:30]


async def amazon_autocomplete(page, keyword: str) -> List[str]:
    """아마존재팬 자동완성 — 원본 방식: 검색 진입 → #twotabsearchtextbox 클릭 → #nav-flyout-searchAjax."""
    try:
        await page.goto(f"https://www.amazon.co.jp/s?k={keyword}&__mk_ja_JP=カタカナ",
                        wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)
    except Exception:
        return []
    box = await page.query_selector("#twotabsearchtextbox")
    if box:
        try:
            await box.click()
            await page.wait_for_timeout(1200)
        except Exception:
            pass
    return await _collect_items(
        page,
        ["#nav-flyout-searchAjax .s-suggestion-container", "[class*='s-suggestion']"],
        keyword,
    )


async def amazon_related(page, keyword: str) -> List[str]:
    """아마존재팬 검색결과의 관련 검색어 (원본 a-box 계열 → 현행 s-related-searches)."""
    try:
        await page.goto(f"https://www.amazon.co.jp/s?k={keyword}&__mk_ja_JP=カタカナ",
                        wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1200)
    except Exception:
        return []
    return await _collect_items(
        page,
        ["[data-component-type='s-related-searches'] a", "[class*='related'] a"],
        keyword,
    )


async def yahoo_related(page, keyword: str) -> List[str]:
    """야후재팬(웹) 관련검색어 — 원본 방식: search.yahoo.co.jp + .Contents__innerGroupFooter li."""
    try:
        await page.goto(f"https://search.yahoo.co.jp/search?p={keyword}",
                        wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1200)
    except Exception:
        return []
    return await _collect_items(
        page,
        [".Contents__innerGroupFooter li", "[class*='Contents__innerGroupFooter'] li"],
        keyword,
    )


async def google_suggest(keyword: str) -> List[str]:
    """Google 자동완성(サジェスト) — 공개 suggest 엔드포인트(JSON). 브라우저 불필요.

    소비자 리서치 의도(とは/使い方/おすすめ/現地でしか 등)까지 잡혀 마켓플레이스
    자동완성과 상호보완. (page 인자 없음 — related.py 에서 별도 처리)
    """
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://suggestqueries.google.com/complete/search",
                params={"client": "firefox", "hl": "ja", "q": keyword},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = r.json()
    except Exception:
        return []
    sugg = data[1] if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list) else []
    out: List[str] = []
    for t in sugg:
        t = (t or "").strip()
        if t and t != keyword and len(t) < 80 and t not in out:
            out.append(t)
    return out[:30]


def make_keyword_dict(keyword_jp: str, source: str) -> Dict:
    """공통 키워드 딕셔너리."""
    cls = {
        "qoo10_related": "연관",
        "qoo10_similar": "유사",
        "qoo10_ad_related": "광고연관",
        "qoo10_autocomplete": "자동완성",
        "google_suggest": "구글자동",
        "amazon_autocomplete": "아마존자동",
        "amazon_related": "아마존연관",
        "yahoo_autocomplete": "야후자동",
        "yahoo_related": "야후연관",
        "yahoo_shopping_autocomplete": "야후쇼핑자동",
        "yahoo_shopping_related": "야후쇼핑연관",
    }.get(source, source)
    return {
        "keyword_jp": keyword_jp,
        "lookup_date": date.today(),
        "classification": cls,
        "index_key": f"{date.today()}_{cls}_{keyword_jp}",
    }
