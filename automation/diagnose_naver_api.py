"""네이버 비공식 JSON API + 모바일 페이지 진단.

브라우저 안 쓰고 httpx 로 직접 fetch. 봇 차단 우회 자체가 불필요한지 확인.

사용:
    python automation/diagnose_naver_api.py
"""
from __future__ import annotations

import asyncio
import json as jsonlib
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx


_THIS_DIR = Path(__file__).resolve().parent
DIAG_DIR = _THIS_DIR / "diagnostics"
DIAG_DIR.mkdir(exist_ok=True)


# 흔히 쓰이는 모바일 UA — 봇 차단 약함
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


TARGETS = [
    {
        "name": "naver_mobile_html",
        "url": "https://msearch.shopping.naver.com/search/all?query=커피",
        "headers": {
            "User-Agent": MOBILE_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://m.naver.com/",
        },
        "kind": "html",
    },
    {
        "name": "naver_api_json",
        "url": (
            "https://search.shopping.naver.com/api/search/all"
            "?query=커피&pagingIndex=1&pagingSize=40&productSet=total&sort=rel"
        ),
        "headers": {
            "User-Agent": DESKTOP_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://search.shopping.naver.com/search/all?query=커피",
            "X-Requested-With": "XMLHttpRequest",
            "logic": "PART",
        },
        "kind": "json",
    },
    {
        "name": "naver_desktop_html",
        "url": "https://search.shopping.naver.com/search/all?query=커피",
        "headers": {
            "User-Agent": DESKTOP_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://www.google.com/",
        },
        "kind": "html",
    },
]


async def fetch_one(client: httpx.AsyncClient, target: dict) -> dict:
    name = target["name"]
    url = target["url"]
    print(f"\n[{name}]")
    print(f"  GET {url}")
    try:
        resp = await client.get(url, headers=target["headers"], timeout=20.0)
    except Exception as e:
        return {"name": name, "ok": False, "error": f"{type(e).__name__}: {e}"}

    body = resp.text
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = "json" if target["kind"] == "json" else "html"
    save_path = DIAG_DIR / f"{name}_{ts}.{ext}"
    save_path.write_text(body, encoding="utf-8")

    info = {
        "name": name,
        "ok": True,
        "status": resp.status_code,
        "char_count": len(body),
        "save_path": str(save_path),
    }

    body_lower = body.lower()
    info["blocked_signals"] = [
        p for p in ["captcha", "차단", "비정상적인", "access denied"]
        if p in body_lower
    ]
    info["price_count"] = len(re.findall(r"\d{1,3}(?:,\d{3})+\s*원", body))

    if target["kind"] == "json":
        # JSON 인지 확인 + 상품 개수 추정
        try:
            data = jsonlib.loads(body)
            info["json_ok"] = True
            # 흔한 키들 — 어디에 상품 리스트가 있는지 탐색
            candidates = []

            def walk(obj, path):
                if isinstance(obj, list) and len(obj) >= 5:
                    # 상품 리스트로 의심
                    sample = obj[0]
                    if isinstance(sample, dict):
                        keys = list(sample.keys())[:10]
                        candidates.append({
                            "path": path, "count": len(obj), "sample_keys": keys,
                        })
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        walk(v, f"{path}.{k}" if path else k)
                elif isinstance(obj, list):
                    for i, v in enumerate(obj[:3]):
                        walk(v, f"{path}[{i}]")

            walk(data, "")
            # 가장 큰 리스트만 상위 3개
            candidates.sort(key=lambda c: c["count"], reverse=True)
            info["json_lists"] = candidates[:3]
        except Exception as e:
            info["json_ok"] = False
            info["json_error"] = str(e)
    else:
        # HTML 셀렉터는 현 단계에선 생략 (저장 후 별도 분석)
        info["img_count"] = body.count("<img")
        info["a_count"] = body.count("<a ")

    return info


def _print(results: list[dict]) -> None:
    print("\n" + "=" * 60)
    print("  네이버 직접 fetch 진단 결과")
    print("=" * 60)
    for r in results:
        print(f"\n[{r['name']}]")
        if not r.get("ok"):
            print(f"  ❌ {r.get('error')}")
            continue
        print(f"  Status      : {r.get('status')}")
        print(f"  본문 크기    : {r['char_count']:,}자")
        if r.get("blocked_signals"):
            print(f"  ⚠️ 차단 의심  : {r['blocked_signals']}")
        else:
            print(f"  차단 의심    : 없음 ✓")
        print(f"  가격 매치    : {r['price_count']}건")
        if "img_count" in r:
            print(f"  img / a     : {r['img_count']} / {r['a_count']}")
        if r.get("json_ok") is True:
            print(f"  JSON parse   : ✓")
            for c in r.get("json_lists", []):
                print(
                    f"    list at '{c['path']}'  count={c['count']}  "
                    f"keys={c['sample_keys']}"
                )
        elif r.get("json_ok") is False:
            print(f"  JSON parse   : ✗ ({r.get('json_error')})")
        print(f"  저장        : {r['save_path']}")
    print()


async def main_async() -> int:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = []
        for t in TARGETS:
            try:
                r = await fetch_one(client, t)
            except Exception as e:
                r = {"name": t["name"], "ok": False, "error": str(e)}
            results.append(r)
    _print(results)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
