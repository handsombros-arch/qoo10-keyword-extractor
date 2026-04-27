"""큐텐 ↔ 한국 cover 이미지 1:1 매칭 트리거.

사용:
    cd C:\\Users\\Admin\\qoo10-keyword-extractor
    python automation/trigger_match_images.py                      # 오늘자 전체
    python automation/trigger_match_images.py --top 5              # 큐텐 1개당 한국 후보 5개
    python automation/trigger_match_images.py --threshold 0.6
    python automation/trigger_match_images.py --limit 50           # 전체 비교 50건만
    python automation/trigger_match_images.py --keywords-jp X Y    # 일본어 키워드 한정
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
    p = argparse.ArgumentParser(description="큐텐 ↔ 한국 cover 이미지 매칭 트리거")
    p.add_argument("--date", help="YYYY-MM-DD (기본 오늘)")
    p.add_argument("--top", type=int, default=3,
                   help="큐텐 1개당 비교할 한국 후보 (기본 3)")
    p.add_argument("--threshold", type=float,
                   help="accepted 임계값 (기본 IMAGE_MATCH_THRESHOLD env → 0.7)")
    p.add_argument("--limit", type=int, help="전체 비교 호출 상한")
    p.add_argument("--keywords-jp", nargs="+", help="일본어 키워드 화이트리스트")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--backend", default=BACKEND)
    args = p.parse_args()

    body: dict = {"per_qoo10_top_n": args.top}
    if args.date: body["date"] = args.date
    if args.threshold is not None: body["threshold"] = args.threshold
    if args.limit: body["limit"] = args.limit
    if args.keywords_jp: body["keywords_jp"] = args.keywords_jp

    print(f"[trigger] POST {args.backend}/api/recommendations/match-images  body={body}")
    try:
        resp = httpx.post(
            f"{args.backend}/api/recommendations/match-images",
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
    scanned = data.get("scanned_qoo10", 0)
    thr = data.get("threshold")
    print(f"[scan] 큐텐 {scanned}장 → 비교 후보 쌍: {candidates}건  (threshold={thr})")
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
                print(f"\n[OK] 매칭 완료")
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
