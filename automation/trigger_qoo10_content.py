"""큐텐 등록용 콘텐츠 LLM 생성 트리거 (Phase 4-B).

사용:
    python automation/trigger_qoo10_content.py                 # 오늘자 accepted
    python automation/trigger_qoo10_content.py --date 2026-04-25 --limit 5
    python automation/trigger_qoo10_content.py --reset
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
    p = argparse.ArgumentParser(description="큐텐 콘텐츠 LLM 생성 트리거")
    p.add_argument("--date", help="YYYY-MM-DD (기본 오늘)")
    p.add_argument("--limit", type=int, help="처리 상한")
    p.add_argument("--all", action="store_true", help="accepted 무관")
    p.add_argument("--reset", action="store_true", help="이미 생성된 케이스도 재생성")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--backend", default=BACKEND)
    args = p.parse_args()

    body: dict = {"only_accepted": not args.all}
    if args.date: body["date"] = args.date
    if args.limit: body["limit"] = args.limit
    if args.reset: body["reset"] = True

    print(f"[trigger] POST {args.backend}/api/products/qoo10/generate-content  body={body}")
    try:
        resp = httpx.post(
            f"{args.backend}/api/products/qoo10/generate-content",
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
    print(f"[scan] 처리 대상: {candidates}건")
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
