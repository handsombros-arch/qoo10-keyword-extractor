"""평소 쓰는 크롬에 attach 해서 네이버 진단.

작동 방식:
  1. 사용자가 평소 크롬을 모두 닫음
  2. automation/launch_chrome_debug.bat 더블클릭 → 디버그 포트(9222) 모드로 크롬 시작
  3. 평소처럼 사용하다가 (또는 곧바로) 이 스크립트 실행
  4. Playwright 가 그 크롬에 connect_over_cdp 로 attach
  5. 새 탭 열어서 네이버 검색 페이지 접근 → 셀렉터 시험
  6. 진단 끝나면 탭만 닫고 크롬 본체는 그대로 둠

사용:
    python automation/diagnose_naver_attach.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright


CDP_URL = "http://localhost:9222"
SEARCH_URL = "https://search.shopping.naver.com/search/all?query=커피"

_THIS_DIR = Path(__file__).resolve().parent
DIAG_DIR = _THIS_DIR / "diagnostics"
DIAG_DIR.mkdir(exist_ok=True)


SELECTORS = [
    "[class*='product_item']",
    "[class*='basicList_item']",
    "[class*='productCard']",
    "[class*='product_inner']",
    "[class*='product_link']",
    "div[data-shp-area-id*='item']",
    "li[class*='_item']",
    "a[href*='/catalog/']",
    "a[href*='/product/']",
    "[class*='Product']",
    "div[data-i]",
]
BLOCK_PATTERNS = ["captcha", "차단", "비정상적인", "Access Denied"]
PRICE_PATTERN = r"\d{1,3}(?:,\d{3})+\s*원"


async def main_async() -> int:
    print(f"디버그 크롬 attach 시도: {CDP_URL}")
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"\n❌ attach 실패: {e}")
            print()
            print("체크리스트:")
            print("  1. 평소 크롬 모두 닫았는지")
            print("  2. automation/launch_chrome_debug.bat 더블클릭 했는지")
            print("  3. 그 후 새 크롬 창이 떴는지")
            print(f"  4. 브라우저 주소창에 {CDP_URL}/json 입력 시 JSON 보이는지")
            return 1

        # 평소 컨텍스트 사용 (사용자 쿠키·세션 그대로)
        contexts = browser.contexts
        if not contexts:
            print("⚠️ 컨텍스트가 없음. 새로 생성")
            context = await browser.new_context()
        else:
            context = contexts[0]
            print(f"기존 컨텍스트 재사용 (열린 탭 {len(context.pages)}개)")

        # 새 탭으로 검색 페이지 열기
        page = await context.new_page()
        print(f"\n검색 페이지 접속: {SEARCH_URL}")
        try:
            await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  ⚠️ goto 경고(무시): {e}")

        await page.wait_for_timeout(3000)
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 600)")
            await page.wait_for_timeout(800)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)

        title = await page.title()
        final_url = page.url
        html = await page.content()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = DIAG_DIR / f"naver_attach_{ts}.html"
        html_path.write_text(html, encoding="utf-8")

        body_lower = html.lower()
        blocked = [p for p in BLOCK_PATTERNS if p.lower() in body_lower]
        price_count = len(re.findall(PRICE_PATTERN, html))

        sel_counts: dict[str, int | str] = {}
        for sel in SELECTORS:
            try:
                els = await page.query_selector_all(sel)
                sel_counts[sel] = len(els)
            except Exception as e:
                sel_counts[sel] = f"err: {type(e).__name__}"

        # 진단 탭만 닫고 브라우저는 유지
        try:
            await page.close()
        except Exception:
            pass
        # CDP attach 시 browser.close() 는 disconnect 만 하고 실제 크롬은 안 닫음
        try:
            await browser.close()
        except Exception:
            pass

    # 리포트
    print("\n" + "=" * 60)
    print("  네이버 attach 진단 결과")
    print("=" * 60)
    print(f"  Title       : {title}")
    print(f"  Final URL   : {final_url}")
    print(f"  HTML        : {len(html):,}자  (img {html.count('<img')}, a {html.count('<a ')})")
    print(f"  가격 매치    : {price_count}건")
    if blocked:
        print(f"  ⚠️ 차단 의심  : {blocked}")
    else:
        print(f"  차단 의심    : 없음 ✓")
    print(f"  HTML 저장    : {html_path}")
    print(f"  셀렉터 후보:")
    for sel, cnt in sel_counts.items():
        ok = isinstance(cnt, int) and cnt > 0
        mark = "✓" if ok else "✗"
        print(f"    {mark} {sel}  →  {cnt}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
