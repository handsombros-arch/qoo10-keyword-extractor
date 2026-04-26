"""오늘 수집된 전체 키워드에 대해 M04 낙찰 재수집 요청."""
import sys
import json
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000"

# 1) 전체 키워드 조회
r = urllib.request.urlopen(f"{BASE}/api/keywords", timeout=60)
d = json.loads(r.read().decode("utf-8"))
today = "2026-04-21"
today_rows = [x for x in d if x.get("lookup_date") == today]

# 2) keyword_jp 중복 제거
uniq = sorted({x["keyword_jp"] for x in today_rows if x.get("keyword_jp")})
print(f"총 {len(today_rows)}행 → unique keyword_jp {len(uniq)}개")

# 3) POST /api/bid/collect
body = json.dumps({"keywords": uniq}).encode("utf-8")
req = urllib.request.Request(
    f"{BASE}/api/bid/collect",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    resp = urllib.request.urlopen(req, timeout=30)
    print("응답:", resp.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print("HTTP 오류:", e.code, e.read().decode("utf-8"))
