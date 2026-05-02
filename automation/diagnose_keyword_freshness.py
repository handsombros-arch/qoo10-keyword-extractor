"""키워드 신선도 진단 (R-5 Phase A).

지난 N일 키워드 누적 통계를 표 형태로 출력.
backend `/api/keywords/freshness` endpoint 호출.

사용:
    python automation/diagnose_keyword_freshness.py            # 기본 14일
    python automation/diagnose_keyword_freshness.py --days 7
    python automation/diagnose_keyword_freshness.py --json     # JSON 그대로

해석 가이드:
- pair_jaccard 0.95+ → 매일 거의 같은 키워드 (개선 필요)
- pair_jaccard 0.7~0.85 → 일부 새 키워드 (정상)
- daily.new 가 매일 50+ → 신선도 양호
- daily.new 가 매일 < 10 → 다양성 개선 필요 (M05 활성화 권장)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

# Windows CMD cp949 회피
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BACKEND = os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")


def _fmt_pct(v: float) -> str:
    return f"{v * 100:5.1f}%"


def _print_human(data: dict) -> None:
    print(f"=== 키워드 신선도 ({data['start_date']} ~ {data['end_date']}, {data['window_days']}일) ===")
    print(f"윈도우 내 누적 unique keyword_jp: {data['total_unique_in_window']}")
    print()

    # 일자별
    print("일자별:")
    print(f"  {'date':<12} {'total':>6} {'new':>6} {'returning':>10} {'new%':>6}")
    for row in data["daily"]:
        new_pct = row["new"] / row["total"] if row["total"] else 0
        print(
            f"  {row['date']:<12} {row['total']:>6} "
            f"{row['new']:>6} {row['returning']:>10} {_fmt_pct(new_pct):>6}"
        )
    print()

    # 인접 일자 자카드
    print("인접 일자 자카드 (1.0 = 완전 동일, 0.0 = 무관):")
    print(f"  {'pair':<26} {'size_a':>6} {'size_b':>6} {'∩':>5} {'jaccard':>8}")
    for p in data["pair_jaccard"]:
        pair = f"{p['a']} → {p['b']}"
        print(
            f"  {pair:<26} {p['size_a']:>6} {p['size_b']:>6} "
            f"{p['intersect']:>5} {p['jaccard']:>8.4f}"
        )
    print()

    # 요약 진단
    pairs = data["pair_jaccard"]
    if pairs:
        avg_jaccard = sum(p["jaccard"] for p in pairs) / len(pairs)
        avg_new = sum(d["new"] for d in data["daily"]) / max(len(data["daily"]), 1)
        print(f"--- 요약 ---")
        print(f"평균 인접 jaccard: {avg_jaccard:.4f}  (낮을수록 다양성 ↑)")
        print(f"일평균 신규 keyword_jp: {avg_new:.1f}건")
        if avg_jaccard >= 0.95:
            print("⚠ 매일 거의 같은 키워드 — M05 연관/유사 활성화 강력 권장")
        elif avg_jaccard >= 0.85:
            print("⚠ 중복률 높음 — M05 활성화 권장")
        elif avg_jaccard >= 0.7:
            print("✓ 일부 다양성 — M05 활성화 시 추가 향상 가능")
        else:
            print("✓ 충분한 다양성")


def main() -> int:
    parser = argparse.ArgumentParser(description="키워드 신선도 진단")
    parser.add_argument("--days", type=int, default=14, help="윈도우 일수 (기본 14, 최대 90)")
    parser.add_argument("--json", action="store_true", help="JSON 출력 (raw)")
    args = parser.parse_args()

    try:
        resp = httpx.get(
            f"{BACKEND}/api/keywords/freshness",
            params={"days": args.days},
            timeout=30.0,
        )
    except Exception as e:
        print(f"[diagnose] 백엔드 호출 실패: {e}", file=sys.stderr)
        return 2
    if resp.status_code != 200:
        print(f"[diagnose] HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return 2

    data = resp.json()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_human(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
