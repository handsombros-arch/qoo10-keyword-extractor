"""확장 키워드 → 한국 검색 자동화 트리거 (Phase 1-D R-1).

사용:
    python automation/trigger_expanded_search.py                       # 전체 expanded
    python automation/trigger_expanded_search.py --limit 5
    python automation/trigger_expanded_search.py --parents メディキューブ 美顔器
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
    p = argparse.ArgumentParser(description="확장 키워드 한국 검색 자동화")
    p.add_argument("--parents", nargs="+", help="특정 parent_jp 만")
    p.add_argument("--limit", type=int, help="처리 상한")
    p.add_argument("--max-results", type=int, default=30, help="키워드당 m08 결과 상한 (기본 30)")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--backend", default=BACKEND)
    args = p.parse_args()

    body: dict = {"max_results": args.max_results}
    if args.parents: body["parents"] = args.parents
    if args.limit: body["limit"] = args.limit

    print(f"[trigger] POST {args.backend}/api/keywords/expanded/run-search  body={body}")
    try:
        resp = httpx.post(
            f"{args.backend}/api/keywords/expanded/run-search",
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
    print(f"[scan] expanded keywords: {candidates}건")
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
