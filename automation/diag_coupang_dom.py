"""쿠팡 페이지 DOM dump 디버그 스크립트.

목적: _fetch_coupang_via_browser_manager 와 동일 흐름으로 페이지 진입 후
HTML/스크린샷 저장 → 정확한 cover image / options 셀렉터 파악.

사용:
    python automation/diag_coupang_dom.py "<URL>" "<상품명>"

저장:
    logs/diag_coupang/<timestamp>/page.html       — 전체 HTML
    logs/diag_coupang/<timestamp>/screenshot.png   — 화면 캡처
    logs/diag_coupang/<timestamp>/summary.txt      — 큰 이미지/옵션 후보 요약
"""
from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

# CMD cp949 회피 — Windows 콘솔에서도 이모지/em-dash 출력
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from playwright.async_api import async_playwright


async def main(product_url: str, product_name: str) -> None:
    out_dir = ROOT / "logs" / "diag_coupang" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[diag] 저장 위치: {out_dir}")

    pw = await async_playwright().start()
    try:
        # CDP attach 는 Chrome 147+ 보안으로 setDownloadBehavior 가 막힘.
        # 프로덕션도 fallback 으로 fresh Chromium + stealth 사용 (browser_manager).
        # 진단도 동일하게 fresh + stealth 로 진행.
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
            locale="ko-KR",
        )
        page = await ctx.new_page()
        try:
            from tf_playwright_stealth import stealth_async
            await stealth_async(page)
        except Exception:
            pass
        try:
            # 1) 검색 페이지 (자연 진입)
            search_url = f"https://www.coupang.com/np/search?q={quote(product_name[:80])}&channel=user"
            print(f"[diag] 검색 진입: {search_url}")
            await page.goto(search_url, referer="https://www.google.com/",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(random.randint(2000, 4000))
            await page.mouse.wheel(0, random.randint(400, 800))
            await page.wait_for_timeout(random.randint(1000, 2000))

            # 2) product url 진입
            print(f"[diag] 상품 페이지 진입: {product_url[:80]}")
            await page.goto(product_url, referer=page.url or "https://www.coupang.com/",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(random.randint(2000, 4000))
            await page.mouse.wheel(0, random.randint(600, 1200))
            await page.wait_for_timeout(random.randint(1000, 2000))
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            title = await page.title()
            print(f"[diag] page.title = {title!r}")
            if "Access Denied" in (title or ""):
                print("[diag] AKAMAI 차단 — 종료")
                return

            # 3) HTML + 스크린샷 저장
            html = await page.content()
            (out_dir / "page.html").write_text(html, encoding="utf-8")
            await page.screenshot(path=str(out_dir / "screenshot.png"), full_page=True)
            print(f"[diag] HTML {len(html)} bytes / screenshot 저장")

            # 4) 핵심 요소 후보 탐색 — JS evaluate 로 한 번에
            summary = await page.evaluate("""
            () => {
              const out = { images: [], options_candidates: [], reviews_candidates: [], price_candidates: [] };

              // 큰 이미지 (200x200 이상, src http)
              for (const img of document.querySelectorAll('img')) {
                const w = img.naturalWidth || img.width || 0;
                const h = img.naturalHeight || img.height || 0;
                const src = img.src || '';
                if (w >= 200 && h >= 200 && src.startsWith('http')) {
                  out.images.push({
                    w, h, src,
                    cls: img.className || '',
                    parent_cls: (img.parentElement && img.parentElement.className) || '',
                    grandparent_cls: (img.parentElement && img.parentElement.parentElement && img.parentElement.parentElement.className) || '',
                  });
                }
              }
              out.images.sort((a, b) => (b.w * b.h) - (a.w * a.h));
              out.images = out.images.slice(0, 15);

              // 옵션 / 리뷰 후보 — class 에 'option' / 'review' / 'rating' / 'star' / 'rate' 포함된 li/select
              const selectors_for_lists = ['li', 'select option', '[role="option"]', '[role="listitem"]'];
              for (const sel of selectors_for_lists) {
                for (const el of document.querySelectorAll(sel)) {
                  const cls = (el.className || '').toString();
                  const parent_cls = (el.parentElement && el.parentElement.className || '').toString();
                  const txt = (el.innerText || el.textContent || '').trim().slice(0, 80);
                  if (!txt) continue;
                  const blob = (cls + ' ' + parent_cls).toLowerCase();
                  if (/option|variant|select|sku/.test(blob)) {
                    out.options_candidates.push({ tag: el.tagName, cls, parent_cls, text: txt });
                  } else if (/review|rating|star|rate|score/.test(blob)) {
                    out.reviews_candidates.push({ tag: el.tagName, cls, parent_cls, text: txt });
                  }
                }
              }
              out.options_candidates = out.options_candidates.slice(0, 30);
              out.reviews_candidates = out.reviews_candidates.slice(0, 30);

              // 가격 후보
              for (const el of document.querySelectorAll('strong, span, em')) {
                const cls = (el.className || '').toString().toLowerCase();
                if (/price|sale|total/.test(cls)) {
                  const txt = (el.innerText || '').trim().slice(0, 40);
                  if (/\\d/.test(txt)) {
                    out.price_candidates.push({ tag: el.tagName, cls, text: txt });
                  }
                }
              }
              out.price_candidates = out.price_candidates.slice(0, 20);

              return out;
            }
            """)

            lines = [
                f"=== Coupang DOM 진단: {product_url} ===",
                f"page.title = {title}",
                f"HTML size = {len(html)} bytes",
                "",
                "─── 큰 이미지 (200x200+) TOP 15 ──────────────",
            ]
            for i, img in enumerate(summary["images"], 1):
                lines.append(
                    f"  {i:2d}. {img['w']}x{img['h']}  cls={img['cls'][:60]!r}"
                    f"\n      parent_cls={img['parent_cls'][:60]!r}"
                    f"\n      grandparent_cls={img['grandparent_cls'][:60]!r}"
                    f"\n      src={img['src'][:100]}"
                )

            lines.append("\n─── 옵션 후보 (class 에 option/variant/select/sku) ──")
            for c in summary["options_candidates"]:
                lines.append(f"  <{c['tag']} cls={c['cls'][:50]!r} parent={c['parent_cls'][:50]!r}> {c['text']!r}")

            lines.append("\n─── 리뷰 후보 (class 에 review/rating/star/rate/score) ──")
            for c in summary["reviews_candidates"]:
                lines.append(f"  <{c['tag']} cls={c['cls'][:50]!r} parent={c['parent_cls'][:50]!r}> {c['text']!r}")

            lines.append("\n─── 가격 후보 ──")
            for c in summary["price_candidates"]:
                lines.append(f"  <{c['tag']} cls={c['cls'][:50]!r}> {c['text']!r}")

            (out_dir / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
            print("\n".join(lines[:5]))
            print(f"\n[diag] 전체 요약: {out_dir / 'summary.txt'}")

        finally:
            try:
                await page.close()
            except Exception:
                pass
            try:
                await ctx.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
    finally:
        await pw.stop()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python diag_coupang_dom.py <URL> <상품명>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
