"""네이버 검색 API 키 검증 스크립트.

backend/.env 의 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 정상 작동하는지 확인.
실제 API 를 두 키워드로 호출해서 응답 + 첫 상품 미리보기 출력.

사용:
    python automation/test_naver_api.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


_THIS_DIR = Path(__file__).resolve().parent
_ROOT = _THIS_DIR.parent
BACKEND_ENV = _ROOT / "backend" / ".env"

load_dotenv(BACKEND_ENV)


NAVER_API_URL = "https://openapi.naver.com/v1/search/shop.json"
TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(s: str) -> str:
    return TAG_RE.sub("", s or "").strip()


async def call_one(client: httpx.AsyncClient, keyword: str, headers: dict) -> dict:
    print(f"\n[검색] '{keyword}'")
    try:
        resp = await client.get(
            NAVER_API_URL,
            headers=headers,
            params={"query": keyword, "display": 5, "start": 1, "sort": "sim"},
            timeout=15,
        )
    except Exception as e:
        return {"keyword": keyword, "ok": False, "error": f"{type(e).__name__}: {e}"}

    print(f"  HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        return {
            "keyword": keyword, "ok": False,
            "status": resp.status_code, "body": resp.text[:300],
        }

    try:
        data = resp.json()
    except Exception as e:
        return {"keyword": keyword, "ok": False, "error": f"JSON parse 실패: {e}"}

    items = data.get("items") or []
    print(f"  총 매칭: {data.get('total', 0):,}건 / 반환: {len(items)}건")
    if items:
        first = items[0]
        print(f"  ─ 1위 상품:")
        print(f"     이름     : {strip_tags(first.get('title', ''))}")
        print(f"     최저가    : {first.get('lprice', '?')}원")
        print(f"     판매처    : {first.get('mallName', '?')}")
        print(f"     링크     : {first.get('link', '?')[:80]}")
    return {"keyword": keyword, "ok": True, "count": len(items)}


async def main_async() -> int:
    print(f".env 경로: {BACKEND_ENV}")
    print(f".env 존재: {BACKEND_ENV.exists()}")

    client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()

    print(f"NAVER_CLIENT_ID     : {'설정됨 (' + client_id[:6] + '...)' if client_id else '❌ 비어있음'}")
    print(f"NAVER_CLIENT_SECRET : {'설정됨' if client_secret else '❌ 비어있음'}")

    if not client_id or not client_secret:
        print("\n❌ backend/.env 에 키가 없습니다.")
        print("   다음 두 줄을 추가하세요:")
        print("     NAVER_CLIENT_ID=발급받은_ID")
        print("     NAVER_CLIENT_SECRET=발급받은_시크릿")
        return 1

    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = []
        for kw in ("커피", "비타민"):
            r = await call_one(client, kw, headers)
            results.append(r)

    # 요약
    print("\n" + "=" * 60)
    print("  결과 요약")
    print("=" * 60)
    all_ok = all(r.get("ok") for r in results)
    for r in results:
        if r.get("ok"):
            print(f"  ✓ '{r['keyword']}'  →  {r['count']}건")
        else:
            err = r.get("error") or f"HTTP {r.get('status')}: {r.get('body', '')[:100]}"
            print(f"  ✗ '{r['keyword']}'  →  {err}")
    print()
    if all_ok:
        print("✅ API 키 정상. m08_naver.py 가 야간 자동화에서 작동합니다.")
        print("   다음 단계: 백엔드(start.pyw) 재시작 후 자동화 실행")
        return 0
    print("❌ 실패 — 위 에러 메시지 확인")
    print("   401: Client ID/Secret 잘못됨 (.env 다시 확인)")
    print("   403: 애플리케이션 등록 시 '검색' API 체크 안 했을 가능성")
    print("   429: 무료 한도(일 25,000건) 초과")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
