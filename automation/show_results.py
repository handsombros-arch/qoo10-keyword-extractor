"""야간 자동화 결과 조회 스크립트.

user_data 테이블의 last_auto_collected:{date} JSON 을 읽어 깔끔하게 출력.

사용:
    python automation/show_results.py              # 오늘 자
    python automation/show_results.py 2026-04-25   # 특정 날짜
    python automation/show_results.py --json       # 원본 JSON
"""
from __future__ import annotations

import asyncio
import json as jsonlib
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv


_THIS_DIR = Path(__file__).resolve().parent
_ROOT = _THIS_DIR.parent
load_dotenv(_ROOT / "backend" / ".env")

# backend 모듈 경로 추가 — 같은 DB 연결 재사용
sys.path.insert(0, str(_ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select       # noqa: E402
from app.db.connection import async_session, engine  # noqa: E402
from app.db.models import UserData  # noqa: E402


async def fetch(target_date: str) -> dict | None:
    storage_key = f"last_auto_collected:{target_date}"
    async with async_session() as s:
        result = await s.execute(select(UserData).where(UserData.key == storage_key))
        row = result.scalar_one_or_none()
    if not row:
        return None
    try:
        return jsonlib.loads(row.data)
    except Exception:
        return None


def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def print_summary(payload: dict) -> None:
    print("\n" + "=" * 78)
    print(f"  야간 자동화 결과 — {payload.get('date')}")
    print("=" * 78)
    print(f"  생성 시각      : {payload.get('generated_at')}")
    print(f"  마진율 임계    : {payload.get('min_margin_rate')}")
    print(f"  마진 통과 후보 : {payload.get('count')}개 / 전체 {payload.get('total_candidates')}개")
    print()

    candidates = payload.get("candidates") or []
    if not candidates:
        print("  (후보 없음)")
        return

    print(f"  {'순':<3} {'키워드(JP)':<18} {'키워드(KR)':<18} "
          f"{'검색량':>7} {'KR%':>5} {'경쟁':>5} {'점수':>6}")
    print("  " + "-" * 76)
    for i, c in enumerate(candidates, 1):
        kr_ratio = f"{(c.get('kr_ratio') or 0) * 100:.0f}%"
        print(
            f"  {i:<3} "
            f"{(c.get('keyword_jp') or '')[:18]:<18} "
            f"{(c.get('keyword_kr') or '')[:18]:<18} "
            f"{_fmt_int(c.get('search_volume')):>7} "
            f"{kr_ratio:>5} "
            f"{c.get('competition_intensity', 0):>5.2f} "
            f"{c.get('final_score', 0):>6.2f}"
        )
    print()

    print("  ─ 상위 5개 상세 ─")
    for i, c in enumerate(candidates[:5], 1):
        margin = c.get("margin") or {}
        ch = c.get("cheapest_domestic") or {}
        print(f"\n  [{i}] {c.get('keyword_jp')}  ({c.get('keyword_kr')})")
        print(f"      큐텐 평균가     : {_fmt_int(c.get('qoo10_avg_jpy'))}円  "
              f"({_fmt_int(c.get('qoo10_count'))}건, "
              f"{_fmt_int(c.get('qoo10_min_jpy'))}~{_fmt_int(c.get('qoo10_max_jpy'))}円)")
        if ch:
            src = ch.get("source", "")
            print(f"      한국 최저가     : {_fmt_int(ch.get('price_krw'))}원  "
                  f"({src})")
            name = (ch.get("product_name") or "")[:60]
            print(f"        └ {name}")
        if margin:
            mr = (margin.get("margin_rate") or 0) * 100
            print(f"      마진            : {_fmt_int(margin.get('profit_krw'))}원  "
                  f"({mr:.1f}%, {margin.get('verdict')}, "
                  f"{margin.get('composition')}, {margin.get('shipping_mode')})")
    print()


async def main_async() -> int:
    args = sys.argv[1:]
    show_json = "--json" in args
    args = [a for a in args if a != "--json"]
    target_date = args[0] if args else str(date.today())

    payload = await fetch(target_date)
    if not payload:
        print(f"❌ {target_date} 데이터 없음.")
        print(f"   key 'last_auto_collected:{target_date}' 가 user_data 테이블에 없습니다.")
        print(f"   야간 자동화를 한 번 실행했는지 확인하세요.")
        await engine.dispose()
        return 1

    if show_json:
        print(jsonlib.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_summary(payload)

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
