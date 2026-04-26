"""네이버 영구 세션 진단.

setup_naver_session.py 로 만든 영구 컨텍스트를 사용해 네이버 쇼핑 검색 페이지를
열고 봇 차단을 통과하는지 / 어떤 셀렉터가 잡히는지 확인.

사용:
    1. python automation/setup_naver_session.py     (한 번만)
    2. python automation/diagnose_naver_session.py  (이거)
"""
from __future__ import annotations

import asyncio
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright


_THIS_DIR = Path(__file__).resolve().parent
SESSION_DIR = _THIS_DIR / "data" / "naver_session"
DIAG_DIR = _THIS_DIR / "diagnostics"
DIAG_DIR.mkdir(exist_ok=True)


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


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


def _find_chrome_path() -> str | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return shutil.which("chrome") or shutil.which("google-chrome")


async def main_async() -> int:
    if not SESSION_DIR.exists() or not any(SESSION_DIR.iterdir()):
        print(f"❌ 세션 디렉토리가 비어있습니다: {SESSION_DIR}")
        print("먼저 셋업을 실행하세요:")
        print("    python automation/setup_naver_session.py")
        return 1

    url = "https://search.shopping.naver.com/search/all?query=커피"
    chrome_path = _find_chrome_path()
    print(f"브라우저: {chrome_path or 'Playwright 번들 Chromium'}")
    print(f"세션 재사용: {SESSION_DIR}")
    print(f"검색 URL: {url}\n")

    async with async_playwright() as p:
        launch_options = {
            "headless": False,
            "viewport": {"width": 1400, "height": 900},
            "user_agent": USER_AGENT,
            "ignore_https_errors": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        }
        if chrome_path:
            launch_options["executable_path"] = chrome_path

        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR), **launch_options
            )
        except Exception as e:
            if "executable_path" in launch_options:
                print(f"시스템 Chrome 실패({e}), 번들 Chromium 으로 재시도")
                launch_options.pop("executable_path", None)
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(SESSION_DIR), **launch_options
                )
            else:
                raise

        page = context.pages[0] if context.pages else await context.new_page()

        print("페이지 접속 중...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  ⚠️  goto 경고: {e}")

        await page.wait_for_timeout(3000)
        # 사람처럼 스크롤
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 600)")
            await page.wait_for_timeout(800)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)

        title = await page.title()
        final_url = page.url
        html = await page.content()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = DIAG_DIR / f"naver_session_{ts}.html"
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

        await context.close()

    # 리포트
    print("\n" + "=" * 60)
    print("  네이버 영구 세션 진단 결과")
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
