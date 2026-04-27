"""한국 상품 이미지 다운로드+비전 트리거 + 진행상황 폴링.

사용:
    cd C:\\Users\\Admin\\qoo10-keyword-extractor
    python automation/trigger_domestic_images.py                       # 오늘자 모든 상품
    python automation/trigger_domestic_images.py --limit 5             # 5장만
    python automation/trigger_domestic_images.py --date 2026-04-25
    python automation/trigger_domestic_images.py --keywords-jp "커피" "토너"
    python automation/trigger_domestic_images.py --reset               # 전체 재처리
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
    p = argparse.ArgumentParser(description="한국 상품 이미지 처리 트리거")
    p.add_argument("--date", help="YYYY-MM-DD (기본 오늘)")
    p.add_argument("--limit", type=int, help="처리 상한")
    p.add_argument("--keywords-jp", nargs="+", help="일본어 키워드 화이트리스트")
    p.add_argument("--reset", action="store_true", help="기존 처리 결과 무시하고 재처리")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--backend", default=BACKEND)
    args = p.parse_args()

    body: dict = {}
    if args.date: body["date"] = args.date
    if args.limit: body["limit"] = args.limit
    if args.keywords_jp: body["keywords_jp"] = args.keywords_jp
    if args.reset: body["reset"] = True

    print(f"[trigger] POST {args.backend}/api/products/domestic/process-images  body={body}")
    try:
        resp = httpx.post(
            f"{args.backend}/api/products/domestic/process-images",
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
    reset_count = data.get("reset_count", 0)
    if reset_count:
        print(f"[reset] {reset_count}행 NULL 로 되돌림")
    if not task_id:
        print(f"[OK] {data.get('message') or '대상 0개'}")
        return 0

    print(f"[OK] 시작됨 - task_id={task_id} / 대상 {candidates}장")
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
                print(f"\n[OK] 처리 완료")
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
