"""큐텐 검색 한 번 트리거 후 task 메시지 + 디버그 파일 확인.

m09 디버깅용. 백엔드 재시작 후 한 번 실행해서 결과 본다.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

KEYWORD = "コーヒー"
DEBUG_DIR = Path(r"C:\Users\Admin\qoo10-keyword-extractor\backend\data\m09_debug")


def trigger():
    print(f"\n[1] POST /api/products/qoo10 (keyword='{KEYWORD}')")
    req = urllib.request.Request(
        "http://localhost:8000/api/products/qoo10",
        data=json.dumps({"keyword": KEYWORD}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req).read().decode("utf-8")
    print(f"    응답: {resp}")


def wait_complete(seconds: int = 15):
    print(f"\n[2] {seconds}초 대기 (검색 + 추출 진행)...")
    time.sleep(seconds)


def latest_qoo10_task():
    print("\n[3] 가장 최근 Qoo10 task 메시지:")
    tasks = json.load(urllib.request.urlopen("http://localhost:8000/api/tasks"))
    qtasks = [t for t in tasks if "Qoo10" in t.get("name", "")]
    if not qtasks:
        print("    Qoo10 task 없음")
        return
    t = qtasks[0]
    print(f"    status  = {t.get('status')}")
    print(f"    message = {t.get('message')}")


def latest_debug_file():
    print(f"\n[4] m09_debug 디렉토리: {DEBUG_DIR}")
    if not DEBUG_DIR.exists():
        print("    ❌ 디렉토리 없음 → m09 새 코드 미적용 (백엔드 재시작 필요)")
        return
    files = sorted(DEBUG_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("    디렉토리는 있지만 .html 파일 없음 (= 0건이 아니었거나 저장 실패)")
        return
    latest = files[0]
    size = latest.stat().st_size
    print(f"    최신 파일: {latest.name}  ({size:,} bytes)")
    print(f"    경로     : {latest}")


if __name__ == "__main__":
    trigger()
    wait_complete()
    latest_qoo10_task()
    latest_debug_file()
