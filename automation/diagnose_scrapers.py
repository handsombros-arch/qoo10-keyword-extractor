"""스크래퍼 진단 스크립트.

큐텐 / 네이버 / 쿠팡 검색 페이지를 직접 열어서 현재 셀렉터가 잘 잡히는지 확인.

수행하는 일:
  1. 각 사이트에 같은 의미의 키워드(コーヒー / 커피 / 커피) 로 검색
  2. 페이지 HTML 통째로 automation/diagnostics/{site}_{timestamp}.html 저장
  3. m07/m08/m09 의 현재 셀렉터로 매치되는 노드 수 측정
  4. 차단/챌린지 페이지 의심 패턴 검사
  5. 가격 텍스트(円 / 원) 매치 수 — 셀렉터와 무관하게 페이지에 상품이 보이는지 추정
  6. 페이지 통계 (HTML 크기, img / a 태그 수)

사용:
    python automation/diagnose_scrapers.py
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
DIAG_DIR = _THIS_DIR / "diagnostics"
DIAG_DIR.mkdir(exist_ok=True)


TARGETS = [
    {
        "name": "qoo10",
        "url": "https://www.qoo10.jp/s/?keyword=コーヒー",
        # m09_qoo10_products.py 의 현재 셀렉터 (2026 새 구조)
        "selectors": [
            "tbody#search_result_item_list > tr[goodscode]",
            "td.td_item .sbj a[title]:not(.txt_brand)",
            "td.td_prc .prc strong",
            "td.td_thmb img",
            # 옛 구조(폴백)
            ".s_item_group .s_item",
        ],
        "block_patterns": ["challenge", "captcha", "robot check"],
        "price_pattern": r"\d{1,3}(?:,\d{3})*\s*円",
    },
    {
        "name": "naver",
        "url": "https://search.shopping.naver.com/search/all?query=커피",
        # m08_naver.py 의 현재 셀렉터
        "selectors": [
            "[class*='product_item']",
            "[class*='basicList_item']",
        ],
        "block_patterns": ["captcha", "차단", "비정상적인"],
        "price_pattern": r"\d{1,3}(?:,\d{3})+\s*원",
    },
    {
        "name": "coupang",
        "url": "https://www.coupang.com/np/search?component=&q=커피&channel=user",
        # m07_coupang.py 의 현재 셀렉터
        "selectors": [
            ".search-product",
            "li.search-product",
        ],
        "block_patterns": [
            "차단", "Access Denied", "captcha",
            "Cloudflare", "비정상적인", "잠시 후 다시",
        ],
        "price_pattern": r"\d{1,3}(?:,\d{3})+\s*원",
    },
]


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _find_chrome_path() -> str | None:
    """시스템 Chrome 경로 — browser_manager 와 동일 패턴."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return shutil.which("chrome") or shutil.which("google-chrome")


async def diagnose_one(context, target: dict) -> dict:
    name = target["name"]
    url = target["url"]
    page = await context.new_page()
    print(f"\n[{name}] {url} 접속 중...", flush=True)

    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            return {"name": name, "ok": False, "error": f"goto 실패: {e}"}

        await page.wait_for_timeout(3000)
        # lazy-load 트리거
        for _ in range(3):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(800)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)

        title = await page.title()
        final_url = page.url
        html = await page.content()

        # 저장
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = DIAG_DIR / f"{name}_{ts}.html"
        html_path.write_text(html, encoding="utf-8")

        # 차단 패턴
        body_lower = html.lower()
        blocked = [p for p in target["block_patterns"] if p.lower() in body_lower]

        # 셀렉터 매치 수
        sel_counts: dict[str, int | str] = {}
        for sel in target["selectors"]:
            try:
                els = await page.query_selector_all(sel)
                sel_counts[sel] = len(els)
            except Exception as e:
                sel_counts[sel] = f"err: {type(e).__name__}"

        # 가격 텍스트 매치 (셀렉터 무관 sanity check)
        price_count = len(re.findall(target["price_pattern"], html))

        return {
            "name": name,
            "ok": True,
            "title": title,
            "final_url": final_url,
            "html_path": str(html_path),
            "char_count": len(html),
            "img_count": html.count("<img"),
            "a_count": html.count("<a "),
            "price_count": price_count,
            "blocked_signals": blocked,
            "sel_counts": sel_counts,
        }
    finally:
        await page.close()


def _print_report(results: list[dict]) -> None:
    print("\n" + "=" * 64)
    print("  스크래퍼 진단 결과")
    print("=" * 64)
    for r in results:
        print(f"\n[{r['name']}]")
        if not r.get("ok"):
            print(f"  ❌ 실패: {r.get('error')}")
            continue
        print(f"  Title       : {r['title']}")
        print(f"  Final URL   : {r['final_url']}")
        print(
            f"  HTML        : {r['char_count']:,}자  "
            f"(img {r['img_count']}, a {r['a_count']})"
        )
        print(f"  가격 매치    : {r['price_count']}건  (페이지에 상품가 텍스트가 보이는지)")
        if r["blocked_signals"]:
            print(f"  ⚠️ 차단 의심  : {r['blocked_signals']}")
        else:
            print(f"  차단 의심    : 없음")
        print(f"  HTML 저장    : {r['html_path']}")
        print(f"  현재 셀렉터:")
        for sel, cnt in r["sel_counts"].items():
            ok = isinstance(cnt, int) and cnt > 0
            mark = "✓" if ok else "✗"
            print(f"    {mark} {sel}  →  {cnt}")
    print("\n" + "=" * 64)
    print("  해석 가이드")
    print("=" * 64)
    print("  - '차단 의심' 표시 + 가격 매치 0  →  봇 차단 (Scrapling 같은 stealth 필요)")
    print("  - 차단 없음 + 가격 매치 ≥ 10 + 셀렉터 ✗  →  셀렉터만 깨짐 (HTML 보고 수정)")
    print("  - 차단 없음 + 가격 매치 0  →  렌더링 미완 또는 다른 검색 페이지로 리디렉션")
    print("  - 셀렉터 ✓                →  현재 동작 OK, 0건 원인은 다른 곳")
    print()


async def main_async() -> int:
    chrome_path = _find_chrome_path()
    print(f"브라우저: {chrome_path or 'Playwright 번들 Chromium'}")
    print(f"진단 결과 저장: {DIAG_DIR}\n")

    async with async_playwright() as p:
        launch_options = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        }
        if chrome_path:
            launch_options["executable_path"] = chrome_path

        try:
            browser = await p.chromium.launch(**launch_options)
        except Exception as e:
            print(f"시스템 Chrome 실패({e}), Chromium 번들로 재시도")
            launch_options.pop("executable_path", None)
            browser = await p.chromium.launch(**launch_options)

        context = await browser.new_context(
            viewport={"width": 1600, "height": 900},
            user_agent=USER_AGENT,
            ignore_https_errors=True,
        )

        results = []
        for target in TARGETS:
            try:
                res = await diagnose_one(context, target)
            except Exception as e:
                res = {"name": target["name"], "ok": False, "error": str(e)}
            results.append(res)

        await browser.close()

    _print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
