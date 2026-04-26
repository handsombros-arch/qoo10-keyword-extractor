"""12개 카테고리 × 3분류 × rank 분포 검증 (UTF-8 고정)."""
import sys
import urllib.request
import json

sys.stdout.reconfigure(encoding="utf-8")

r = urllib.request.urlopen("http://localhost:8000/api/keywords", timeout=30)
d = json.loads(r.read().decode("utf-8"))
today = "2026-04-21"
rows = [x for x in d if x.get("lookup_date") == today]
print(f"오늘({today}) 총 {len(rows)}행\n")

CATS = [
    "01.종합", "02.여성패션", "03.뷰티&화장품", "04.남성&스포츠",
    "05.디지털", "06.홈&생활", "07.식품", "08.엔터테인먼트&e티켓",
    "09.베이비&키즈", "10.모바일", "11.펫 푸드&용품", "12.서플리먼트&다이어트",
]
CLS = ["1.주요", "2.일간", "3.주간"]

print(f"{'카테고리':<22} {'주요':>5} {'일간':>5} {'주간':>5} {'합계':>5} | top1")
print("-" * 90)
for c in CATS:
    counts = []
    top1 = "-"
    for cls in CLS:
        sub = [x for x in rows if x.get("category") == c and x.get("classification") == cls]
        counts.append(len(sub))
        if cls == "1.주요" and sub:
            r1 = min(sub, key=lambda x: x.get("rank") or 9999)
            top1 = f"{r1.get('keyword_jp','?')} ({r1.get('keyword_kr','')})"
    total = sum(counts)
    print(f"{c:<22} {counts[0]:>5} {counts[1]:>5} {counts[2]:>5} {total:>5} | {top1}")
