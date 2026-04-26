"""Scrapling StealthyFetcher 로 네이버 / 쿠팡 진단.

기본 Playwright 가 봇 차단당한 두 사이트를 Scrapling 의 stealth 모드로 다시 시도한다.

수행:
  1. 네이버 / 쿠팡 검색 페이지를 StealthyFetcher 로 fetch
  2. HTML을 automation/diagnostics/scrapling_{site}_{ts}.html 에 저장
  3. 가격 매치 / 차단 패턴 / 페이지 통계 출력
  4. 일반 셀렉터 후보 몇 가지를 시험해서 어떤 게 잡히는지 표시

선행 설치:
    pip install "scrapling[fetchers]"
    scrapling install         # camoufox (stealth Firefox) 한 번만 다운로드

사용:
    python automation/diagnose_scrapling.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
DIAG_DIR = _THIS_DIR / "diagnostics"
DIAG_DIR.mkdir(exist_ok=True)


TARGETS = [
    {
        "name": "naver",
        "url": "https://search.shopping.naver.com/search/all?query=커피",
        # 네이버 쇼핑 후보 셀렉터 (실험용 — 어떤 게 잡히는지 봄)
        "selectors": [
            "[class*='product_item']",
            "[class*='basicList_item']",
            "[class*='productCard']",
            "[class*='product_inner']",
            "[class*='product_link']",
            "div[data-shp-area-id*='item']",
            "li[class*='_item']",
            "a[href*='/catalog/']",
            "a[href*='/product/']",
        ],
        "block_patterns": ["captcha", "차단", "비정상적인", "Access Denied"],
        "price_pattern": r"\d{1,3}(?:,\d{3})+\s*원",
    },
    {
        "name": "coupang",
        "url": "https://www.coupang.com/np/search?component=&q=커피&channel=user",
        "selectors": [
            ".search-product",
            "li.search-product",
            "[class*='ProductUnit']",
            "[class*='productSearch']",
            "li[class*='search']",
            "a[href*='/vp/products/']",
            "li[data-product-id]",
            "[data-id]",
        ],
        "block_patterns": [
            "차단", "Access Denied", "captcha",
            "Cloudflare", "잠시 후 다시", "비정상적인",
        ],
        "price_pattern": r"\d{1,3}(?:,\d{3})+\s*원",
    },
]


async def fetch_one(target: dict) -> dict:
    name = target["name"]
    url = target["url"]
    print(f"\n[{name}] {url}\n  Stealth fetch 중... (페이지 렌더링 대기 ~10초)", flush=True)

    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as e:
        return {"name": name, "ok": False, "error": f"scrapling import 실패: {e}"}

    # 강화된 옵션 — 안 받는 옵션이 있으면 단계적으로 빼면서 재시도
    aggressive_kwargs = {
        "headless": False,           # 진짜 창 띄우기 — headless 탐지 우회
        "network_idle": True,
        "google_search": True,       # google 검색에서 들어온 것처럼
        "block_images": False,
        "humanize": True,            # 사람 같은 마우스/스크롤
        "solve_cloudflare": True,    # CF 챌린지 자동 풀기 (쿠팡용)
        "wait": 5000,                # 페이지 로드 후 대기 (ms)
    }

    page = None
    last_err = None
    # 인자 안 받는 옵션 있으면 점진적으로 제거
    optional_keys = ["solve_cloudflare", "humanize", "google_search"]
    for attempt in range(len(optional_keys) + 1):
        try:
            page = await asyncio.to_thread(
                StealthyFetcher.fetch, url, **aggressive_kwargs
            )
            break
        except TypeError as e:
            # 알 수 없는 키워드 → 하나씩 빼서 재시도
            last_err = e
            if attempt < len(optional_keys):
                removed = aggressive_kwargs.pop(optional_keys[attempt], None)
                print(f"  옵션 '{optional_keys[attempt]}' 미지원, 제거하고 재시도", flush=True)
                continue
            return {"name": name, "ok": False, "error": f"fetch TypeError: {e}"}
        except Exception as e:
            return {"name": name, "ok": False, "error": f"fetch 실패: {type(e).__name__}: {e}"}

    if page is None:
        return {"name": name, "ok": False, "error": f"모든 옵션 시도 실패: {last_err}"}

    # Scrapling Adaptor 객체에서 HTML 추출
    html = ""
    status = None
    try:
        status = getattr(page, "status", None)
        # 버전별 속성: html_content / body / pretty / text
        for attr in ("html_content", "body", "pretty", "text"):
            v = getattr(page, attr, None)
            if isinstance(v, str) and len(v) > len(html):
                html = v
        if not html:
            html = str(page)
    except Exception as e:
        return {"name": name, "ok": False, "error": f"html 추출 실패: {e}"}

    if not html:
        return {"name": name, "ok": False, "error": "HTML 비어있음"}

    # 저장
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = DIAG_DIR / f"scrapling_{name}_{ts}.html"
    html_path.write_text(html, encoding="utf-8")

    # 차단 패턴
    body_lower = html.lower()
    blocked = [p for p in target["block_patterns"] if p.lower() in body_lower]

    # 가격 텍스트
    price_count = len(re.findall(target["price_pattern"], html))

    # 셀렉터 매치 — Scrapling 의 .css() 사용
    sel_counts: dict[str, int | str] = {}
    for sel in target["selectors"]:
        try:
            els = page.css(sel)
            sel_counts[sel] = len(els) if hasattr(els, "__len__") else 0
        except Exception as e:
            sel_counts[sel] = f"err: {type(e).__name__}"

    return {
        "name": name,
        "ok": True,
        "status": status,
        "html_path": str(html_path),
        "char_count": len(html),
        "img_count": html.count("<img"),
        "a_count": html.count("<a "),
        "price_count": price_count,
        "blocked_signals": blocked,
        "sel_counts": sel_counts,
    }


def _print_report(results: list[dict]) -> None:
    print("\n" + "=" * 64)
    print("  Scrapling 진단 결과")
    print("=" * 64)
    for r in results:
        print(f"\n[{r['name']}]")
        if not r.get("ok"):
            print(f"  ❌ 실패: {r.get('error')}")
            continue
        print(f"  HTTP status : {r.get('status')}")
        print(
            f"  HTML        : {r['char_count']:,}자  "
            f"(img {r['img_count']}, a {r['a_count']})"
        )
        print(f"  가격 매치    : {r['price_count']}건")
        if r["blocked_signals"]:
            print(f"  ⚠️ 차단 의심  : {r['blocked_signals']}")
        else:
            print(f"  차단 의심    : 없음 ✓")
        print(f"  HTML 저장    : {r['html_path']}")
        print(f"  셀렉터 후보:")
        for sel, cnt in r["sel_counts"].items():
            ok = isinstance(cnt, int) and cnt > 0
            mark = "✓" if ok else "✗"
            print(f"    {mark} {sel}  →  {cnt}")
    print()


async def main_async() -> int:
    results = []
    for target in TARGETS:
        try:
            res = await fetch_one(target)
        except Exception as e:
            res = {"name": target["name"], "ok": False, "error": str(e)}
        results.append(res)

    _print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
