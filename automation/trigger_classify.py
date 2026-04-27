"""카테고리 분류 백엔드 작업을 한 줄로 시작 + 진행상황 폴링.

사용:
    cd C:\\Users\\Admin\\qoo10-keyword-extractor
    python automation/trigger_classify.py                    # 오늘자 전체
    python automation/trigger_classify.py --limit 5          # 5개 unique 키워드만
    python automation/trigger_classify.py --date 2026-04-26  # 특정 날짜
    python automation/trigger_classify.py --no-wait          # 시작만 하고 종료
"""
from __future__ import annotations

import argparse
import sys
import time

# Windows 의 cp949 콘솔은 em dash 등 일부 유니코드 문자 인코딩 실패.
# stdout 을 utf-8 로 재설정 (Python 3.7+).
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx

BACKEND = "http://localhost:8000"
POLL_INTERVAL = 3


def main() -> int:
    p = argparse.ArgumentParser(description="카테고리 분류 트리거 + 폴링")
    p.add_argument("--date", help="YYYY-MM-DD (기본 오늘)")
    p.add_argument("--limit", type=int, help="처리할 unique 키워드 상한")
    p.add_argument(
        "--reset-label",
        help="이 라벨로 분류된 행을 NULL 로 되돌리고 재분류 (예: --reset-label 기타)",
    )
    p.add_argument("--no-wait", action="store_true", help="시작만 하고 폴링 안 함")
    p.add_argument("--backend", default=BACKEND, help="백엔드 URL (기본 localhost:8000)")
    args = p.parse_args()

    body: dict = {}
    if args.date:
        body["date"] = args.date
    if args.limit:
        body["limit"] = args.limit
    if args.reset_label:
        body["reset_label"] = args.reset_label

    print(f"[trigger] POST {args.backend}/api/keywords/classify-categories  body={body}")
    try:
        resp = httpx.post(
            f"{args.backend}/api/keywords/classify-categories",
            json=body,
            timeout=30.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        print(f"[ERR] HTTP {e.response.status_code}: {e.response.text[:300]}")
        return 1
    except Exception as e:
        print(f"[ERR] 호출 실패: {type(e).__name__}: {e}")
        return 1

    data = resp.json()
    if data.get("error"):
        print(f"[ERR] {data['error']}")
        return 1

    task_id = data.get("task_id")
    candidates = data.get("candidates", 0)
    reset_count = data.get("reset_count", 0)
    if reset_count:
        print(f"[reset] {reset_count}행을 NULL 로 되돌림 (재분류 대상에 포함)")
    if not task_id:
        print(f"[OK] {data.get('message') or '대상 0개 - 모두 이미 분류됨'}")
        return 0

    print(f"[OK] 시작됨 - task_id={task_id} / 대상 unique 키워드 {candidates}개")

    if args.no_wait:
        print(f"\n진행상황 보기:")
        print(f"  curl {args.backend}/api/tasks/{task_id}")
        return 0

    print(f"\n[poll] {POLL_INTERVAL}초 간격 폴링… (Ctrl+C 로 중단 가능, 작업은 백엔드에서 계속)")
    last_msg = ""
    try:
        while True:
            try:
                r = httpx.get(f"{args.backend}/api/tasks/{task_id}", timeout=15.0)
                r.raise_for_status()
                t = r.json()
            except Exception as e:
                print(f"  [poll] 조회 실패(재시도): {e}")
                time.sleep(POLL_INTERVAL)
                continue

            status = t.get("status")
            msg = t.get("message", "")
            prog = t.get("progress", 0)
            total = t.get("total", 0)

            if msg != last_msg:
                print(f"  [{status}] {prog}/{total} — {msg}")
                last_msg = msg

            if status == "completed":
                print(f"\n[OK] 분류 완료")
                return 0
            if status == "failed":
                print(f"\n[FAIL] {msg}")
                return 1

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print(f"\n[중단] 폴링만 종료. 작업은 백엔드에서 계속 진행 중.")
        print(f"  나중에 확인: curl {args.backend}/api/tasks/{task_id}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
