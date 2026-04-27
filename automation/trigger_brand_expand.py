"""브랜드 키워드 확장 트리거 (Phase 1-D, 명세 3.3#1~3).

사용:
    python automation/trigger_brand_expand.py --date 2026-04-27 --qoo10-date 2026-04-25
    python automation/trigger_brand_expand.py --limit 5 --top 10
    python automation/trigger_brand_expand.py --brands 메디큐브 달바
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
POLL_INTERVAL = 3


def main() -> int:
    p = argparse.ArgumentParser(description="브랜드 키워드 확장 (Phase 1-D)")
    p.add_argument("--date", help="keywords lookup_date (기본 오늘)")
    p.add_argument("--qoo10-date", help="큐텐 상품 lookup_date (기본 = date)")
    p.add_argument("--top-n", type=int, default=10, help="큐텐 상위 N개 상품명 (기본 10)")
    p.add_argument("--limit", type=int, help="처리할 brand 키워드 상한")
    p.add_argument("--brands", nargs="+", help="특정 brand_kr 만 (예: 메디큐브 달바)")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--backend", default=BACKEND)
    args = p.parse_args()

    body: dict = {"top_n": args.top_n}
    if args.date: body["date"] = args.date
    if args.qoo10_date: body["qoo10_date"] = args.qoo10_date
    if args.limit: body["limit"] = args.limit
    if args.brands: body["brands"] = args.brands

    print(f"[trigger] POST {args.backend}/api/keywords/expand-brand  body={body}")
    try:
        resp = httpx.post(
            f"{args.backend}/api/keywords/expand-brand",
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
    print(f"[scan] is_brand=1 키워드: {candidates}건 (top_n={data.get('top_n')})")
    if not task_id:
        print(f"[OK] {data.get('message') or '대상 0건'}")
        return 0

    print(f"[OK] 시작됨 - task_id={task_id}")
    if args.no_wait:
        return 0

    print(f"\n[poll] {POLL_INTERVAL}초 간격 폴링…")
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
        print(f"\n[중단] 폴링만 종료.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
