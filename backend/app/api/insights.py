from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_session
from app.db.models import Keyword

router = APIRouter(prefix="/api/insights", tags=["insights"])


async def _get_latest_date(session: AsyncSession, category: Optional[str] = None) -> Optional[date]:
    stmt = select(func.max(Keyword.lookup_date))
    if category:
        stmt = stmt.where(Keyword.category == category)
    result = await session.execute(stmt)
    return result.scalar()


async def _get_date_near(session: AsyncSession, target: date, category: Optional[str] = None) -> Optional[date]:
    """target 이하 가장 가까운 날짜 반환."""
    stmt = select(Keyword.lookup_date).where(Keyword.lookup_date <= target)
    if category:
        stmt = stmt.where(Keyword.category == category)
    stmt = stmt.order_by(Keyword.lookup_date.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar()


@router.get("/new")
async def new_keywords(
    days_back: int = 1,
    category: Optional[str] = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    """최신 일자 중 N일 전에는 없던 키워드 목록."""
    latest = await _get_latest_date(session, category)
    if latest is None:
        return {"message": "데이터 없음", "new_keywords": [], "latest": None, "compare_to": None}
    compare_target = latest - timedelta(days=days_back)
    compare_date = await _get_date_near(session, compare_target, category)

    # 비교 기준일의 keyword_jp 집합
    past_stmt = select(Keyword.keyword_jp.distinct()).where(Keyword.lookup_date == compare_date)
    if category:
        past_stmt = past_stmt.where(Keyword.category == category)
    past_kws = {r[0] for r in (await session.execute(past_stmt)).all()}

    # 최신 일자에만 있는 키워드
    curr_stmt = select(Keyword).where(Keyword.lookup_date == latest)
    if category:
        curr_stmt = curr_stmt.where(Keyword.category == category)
    curr_rows = (await session.execute(curr_stmt)).scalars().all()

    new_list = []
    seen = set()
    for r in curr_rows:
        if r.keyword_jp in past_kws:
            continue
        if r.keyword_jp in seen:
            continue
        seen.add(r.keyword_jp)
        new_list.append({
            "keyword_jp": r.keyword_jp,
            "keyword_kr": r.keyword_kr,
            "category": r.category,
            "classification": r.classification,
            "rank": r.rank,
            "search_volume_weekly": r.search_volume_weekly,
            "lookup_date": str(r.lookup_date),
        })
    # 순위 좋은 순
    new_list.sort(key=lambda x: x["rank"] or 99999)
    return {
        "latest": str(latest),
        "compare_to": str(compare_date) if compare_date else None,
        "count": len(new_list),
        "new_keywords": new_list[:limit],
    }


@router.get("/changes")
async def keyword_changes(
    days_back: int = 1,
    category: Optional[str] = None,
    classification: Optional[str] = None,
    top_n: int = 30,
    session: AsyncSession = Depends(get_session),
):
    """최신 일자 vs N일 전의 순위/검색량 변화 Top N 상승/하락."""
    latest = await _get_latest_date(session, category)
    if latest is None:
        return {"message": "데이터 없음", "rising": [], "falling": []}
    compare_target = latest - timedelta(days=days_back)
    compare_date = await _get_date_near(session, compare_target, category)

    if compare_date is None or compare_date == latest:
        return {
            "latest": str(latest),
            "compare_to": None,
            "message": f"{days_back}일 전 비교 데이터 없음",
            "rising": [], "falling": [],
        }

    def build_stmt(d):
        s = select(Keyword).where(Keyword.lookup_date == d)
        if category:
            s = s.where(Keyword.category == category)
        if classification:
            s = s.where(Keyword.classification == classification)
        return s

    curr_rows = (await session.execute(build_stmt(latest))).scalars().all()
    past_rows = (await session.execute(build_stmt(compare_date))).scalars().all()

    # (keyword_jp, category, classification) 키로 비교
    def key(r):
        return (r.keyword_jp, r.category, r.classification)

    past_map = {key(r): r for r in past_rows}

    changes = []
    for c in curr_rows:
        p = past_map.get(key(c))
        if not p:
            continue
        if c.rank is None or p.rank is None:
            continue
        rank_delta = (p.rank or 0) - (c.rank or 0)  # 양수 = 상승
        sv_old = p.search_volume_weekly or 0
        sv_new = c.search_volume_weekly or 0
        sv_pct = ((sv_new - sv_old) / sv_old * 100) if sv_old > 0 else None
        changes.append({
            "keyword_jp": c.keyword_jp,
            "keyword_kr": c.keyword_kr,
            "category": c.category,
            "classification": c.classification,
            "rank_old": p.rank,
            "rank_new": c.rank,
            "rank_delta": rank_delta,
            "search_volume_old": sv_old,
            "search_volume_new": sv_new,
            "search_volume_pct": round(sv_pct, 1) if sv_pct is not None else None,
        })

    rising = sorted(changes, key=lambda x: -x["rank_delta"])[:top_n]
    falling = sorted(changes, key=lambda x: x["rank_delta"])[:top_n]

    return {
        "latest": str(latest),
        "compare_to": str(compare_date),
        "rising": rising,
        "falling": falling,
    }


@router.get("/timeseries")
async def keyword_timeseries(
    keyword_jp: str,
    days: int = 30,
    session: AsyncSession = Depends(get_session),
):
    """특정 키워드의 일자별 순위/검색량 추이."""
    end = date.today()
    start = end - timedelta(days=days)
    stmt = (
        select(Keyword)
        .where(Keyword.keyword_jp == keyword_jp)
        .where(Keyword.lookup_date >= start)
        .order_by(Keyword.lookup_date, Keyword.category, Keyword.classification)
    )
    rows = (await session.execute(stmt)).scalars().all()
    # 같은 날짜에 여러 카테고리/분류 있을 수 있음 → 순위 최소값(가장 좋은)과 검색량 평균
    from collections import defaultdict
    daily: dict[str, dict] = defaultdict(lambda: {"rank": None, "search_volume": 0, "count": 0, "samples": []})
    for r in rows:
        d = str(r.lookup_date)
        daily[d]["samples"].append({
            "category": r.category,
            "classification": r.classification,
            "rank": r.rank,
            "search_volume_weekly": r.search_volume_weekly,
        })
        if r.rank is not None:
            cur = daily[d]["rank"]
            daily[d]["rank"] = r.rank if cur is None else min(cur, r.rank)
        if r.search_volume_weekly:
            daily[d]["search_volume"] += r.search_volume_weekly
            daily[d]["count"] += 1

    series = []
    for d in sorted(daily.keys()):
        info = daily[d]
        series.append({
            "date": d,
            "rank": info["rank"],
            "search_volume": int(info["search_volume"] / info["count"]) if info["count"] else None,
            "samples": info["samples"],
        })

    return {"keyword_jp": keyword_jp, "series": series}
