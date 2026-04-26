"""4/21 카테고리별 rank 1-15를 출력해 참조 데이터와 비교 (UTF-8 고정)."""
import sys
import urllib.request
import json

sys.stdout.reconfigure(encoding="utf-8")

r = urllib.request.urlopen("http://localhost:8000/api/keywords", timeout=30)
d = json.loads(r.read().decode("utf-8"))
today = "2026-04-21"
targets = [
    ("01.종합", "1.주요"),
    ("07.식품", "1.주요"),
    ("07.식품", "2.일간"),
    ("07.식품", "3.주간"),
    ("12.서플리먼트&다이어트", "1.주요"),
    ("12.서플리먼트&다이어트", "2.일간"),
    ("12.서플리먼트&다이어트", "3.주간"),
]
for cat, cls in targets:
    rows = [
        x
        for x in d
        if x.get("lookup_date") == today
        and x.get("category") == cat
        and x.get("classification") == cls
    ]
    rows.sort(key=lambda x: x.get("rank") or 9999)
    print(f"\n=== {cat} / {cls} (총 {len(rows)}행) ===")
    for x in rows[:15]:
        print(
            f"  rank={x.get('rank')}  kw={x.get('keyword_jp')}  주평={x.get('search_volume_weekly')}  전날={x.get('search_volume_daily')}"
        )
