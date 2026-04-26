"""네이버 검색 한 번 트리거 후 task 메시지 확인.

m08 + BGE-M3 임베딩 매칭 검증용. 백엔드 재시작 후 한 번 실행해서 결과 본다.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

KEYWORD = "커피"


def trigger():
    print(f"\n[1] POST /api/products/naver (keyword='{KEYWORD}')")
    req = urllib.request.Request(
        "http://localhost:8000/api/products/naver",
        data=json.dumps({"keyword": KEYWORD}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req).read().decode("utf-8")
    print(f"    응답: {resp}")


def wait(seconds: int = 15):
    print(f"\n[2] {seconds}초 대기 (BGE-M3 첫 로드 + 임베딩 + 매칭)...")
    time.sleep(seconds)


def latest_naver_task():
    print("\n[3] 가장 최근 네이버 task 메시지:")
    tasks = json.load(urllib.request.urlopen("http://localhost:8000/api/tasks"))
    ntasks = [t for t in tasks if "네이버" in t.get("name", "")]
    if not ntasks:
        print("    네이버 task 없음")
        return
    t = ntasks[0]
    print(f"    status  = {t.get('status')}")
    print(f"    message = {t.get('message')}")


if __name__ == "__main__":
    trigger()
    wait()
    latest_naver_task()
