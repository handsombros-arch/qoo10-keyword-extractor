"""한국 상품 상세 페이지 진입 트리거 (옵션/배송비/이미지).

사용:
    cd C:\\Users\\Admin\\qoo10-keyword-extractor
    python automation/trigger_domestic_details.py                       # 오늘자 accepted 케이스 전부
    python automation/trigger_domestic_details.py --date 2026-04-25
    python automation/trigger_domestic_details.py --limit 5             # 5건만
    python automation/trigger_domestic_details.py --sources coupang naver
    python automation/trigger_domestic_details.py --all                 # accepted 무관 (전체)
"""
from __future__ import annotations

import argparse
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx

BACKEND = "http://localhost:8000"
POLL_INTERVAL = 5


def main() -> int:
    p = argparse.ArgumentParser(description="한국 상품 옵션 채움 트리거")
    p.add_argument("--date", help="YYYY-MM-DD (기본 오늘)")
    p.add_argument("--limit", type=int, help="처리 상한")
    p.add_argument("--sources", nargs="+", default=["naver", "coupang"],
                   help="쇼핑몰 (기본 naver coupang)")
    p.add_argument("--all", action="store_true",
                   help="accepted 무관 — 전체 한국 상품")
    p.add_argument("--reset", action="store_true",
                   help="이미 처리된 케이스도 재처리")
    p.add_argument("--scrape", action="store_true",
                   help="상세 페이지 진입 시도 (Playwright/Scrapling — 봇 차단 다발). "
                        "기본은 api_only 모드 (m08 검색 결과만 사용)")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--backend", default=BACKEND)
    args = p.parse_args()

    body: dict = {
        "only_accepted": not args.all,
        "sources": args.sources,
        "mode": "scrape" if args.scrape else "api_only",
    }
    if args.date: body["date"] = args.date
    if args.limit: body["limit"] = args.limit
    if args.reset: body["reset"] = True

    print(f"[trigger] POST {args.backend}/api/products/domestic/scrape-details  body={body}")
    try:
        resp = httpx.post(
            f"{args.backend}/api/products/domestic/scrape-details",
            json=body, timeout=30.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        print(f"[ERR] HTTP {e.response.status_code}: {e.response.text[:300]}")
        return 1
    except Exception as e:
        print(f"[ERR] {type(e).__name__}: {e}")
        return 1

    data = resp.json()
    if data.get("error"):
        print(f"[ERR] {data['error']}")
        return 1

    task_id = data.get("task_id")
    candidates = data.get("candidates", 0)
    print(f"[scan] 처리 대상: {candidates}건  (only_accepted={data.get('only_accepted')}, sources={data.get('sources')})")
    if not task_id:
        print(f"[OK] {data.get('message') or '대상 0건'}")
        return 0

    print(f"[OK] 시작됨 - task_id={task_id}")
    if args.no_wait:
        print(f"\n진행: curl {args.backend}/api/tasks/{task_id}")
        return 0

    print(f"\n[poll] {POLL_INTERVAL}초 간격 폴링… (Ctrl+C 로 중단)")
    last_msg = ""
    try:
        while True:
            try:
                r = httpx.get(f"{args.backend}/api/tasks/{task_id}", timeout=15.0)
                r.raise_for_status()
                t = r.json()
            except Exception as e:
                print(f"  [poll] 조회 실패(재시도): {e}")
                time.sleep(POLL_INTERVAL); continue

            status = t.get("status")
            msg = t.get("message", "")
            prog = t.get("progress", 0)
            total = t.get("total", 0)

            if msg != last_msg:
                print(f"  [{status}] {prog}/{total} — {msg}")
                last_msg = msg

            if status == "completed":
                print(f"\n[OK] 완료")
                return 0
            if status == "failed":
                print(f"\n[FAIL] {msg}")
                return 1
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print(f"\n[중단] 폴링만 종료. 작업은 백엔드에서 계속.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
