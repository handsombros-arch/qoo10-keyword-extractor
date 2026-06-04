"""한국 트렌드 랭킹(올리브영) 수집을 한 줄로 시작 + 진행상황 폴링.

사용:
    cd C:\\Users\\Admin\\qoo10-keyword-extractor
    python automation/trigger_kr_trend.py                # 전 카테고리 30위
    python automation/trigger_kr_trend.py --top 20       # 20위까지
    python automation/trigger_kr_trend.py --no-wait      # 시작만

전제: 백엔드(start.pyw)가 실행 중이어야 함. AKAMAI 우회 위해 실 Chrome 사용.
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
    p = argparse.ArgumentParser(description="한국 트렌드(올리브영) 수집 트리거")
    p.add_argument("--top", type=int, default=30, help="카테고리별 상위 N위 (기본 30)")
    p.add_argument("--no-wait", action="store_true", help="시작만 하고 폴링 안 함")
    p.add_argument("--backend", default=BACKEND)
    args = p.parse_args()

    print(f"[trigger] POST {args.backend}/api/kr-trend/collect?top_n={args.top}")
    try:
        resp = httpx.post(f"{args.backend}/api/kr-trend/collect",
                          params={"top_n": args.top}, timeout=30.0)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERR] 호출 실패: {type(e).__name__}: {e}")
        return 1

    data = resp.json()
    task_id = data.get("master_task_id")
    if not task_id:
        print(f"[?] {data}")
        return 1
    print(f"[OK] 시작됨 - task_id={task_id}")

    if args.no_wait:
        print(f"진행: curl {args.backend}/api/tasks/{task_id}")
        return 0

    print(f"[poll] {POLL_INTERVAL}초 간격…")
    last = ""
    try:
        while True:
            try:
                t = httpx.get(f"{args.backend}/api/tasks/{task_id}", timeout=15.0).json()
            except Exception as e:
                print(f"  [poll] 재시도: {e}"); time.sleep(POLL_INTERVAL); continue
            status, msg = t.get("status"), t.get("message", "")
            if msg != last:
                print(f"  [{status}] {t.get('progress',0)}/{t.get('total',0)} — {msg}")
                last = msg
            if status == "completed":
                print("\n[OK] 수집 완료"); return 0
            if status == "failed":
                print(f"\n[FAIL] {msg}"); return 1
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print(f"\n[중단] 폴링만 종료. 백엔드에서 계속 진행.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
