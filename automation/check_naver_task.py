"""가장 최근 네이버 task 상태/메시지 조회."""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

tasks = json.load(urllib.request.urlopen("http://localhost:8000/api/tasks"))
ntasks = [t for t in tasks if "네이버" in t.get("name", "")]

if not ntasks:
    print("네이버 task 없음")
else:
    print(f"네이버 task: {len(ntasks)}개. 최근 3개:")
    for t in ntasks[:3]:
        print(f"  status  = {t.get('status')}")
        print(f"  message = {t.get('message')}")
        print()
