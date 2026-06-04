"""한국 트렌드 랭킹 (올리브영/다이소) 수집·조회 API (R-9, 2026-06-04)."""
import asyncio
from datetime import date

from fastapi import APIRouter
from sqlalchemy import select, delete, and_

from app.browser.manager import browser_manager
from app.db.connection import async_session
from app.db.models import KrTrendRanking
from app.scrapers.kr_trend_oliveyoung import crawl_oliveyoung_rankings, CATEGORIES
from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/kr-trend", tags=["kr-trend"])


async def _save_rankings(source: str, rows: list) -> int:
    """날짜별 누적 저장 — 과거 데이터 절대 미삭제.

    오늘+source 조합만 (재수집 갱신 위해) 삭제 후 적재. rows 가 비면 호출하지 않음
    (= 0건 수집 시 기존 오늘 데이터도 보존).
    """
    if not rows:
        return 0
    today = date.today()
    async with async_session() as session:
        await session.execute(delete(KrTrendRanking).where(and_(
            KrTrendRanking.source == source,
            KrTrendRanking.lookup_date == today,
        )))
        for r in rows:
            session.add(KrTrendRanking(**r))
        await session.commit()
    return len(rows)


@router.post("/collect")
async def collect_kr_trend(top_n: int = 30):
    """올리브영 전 메인 카테고리 판매랭킹 top_n 수집 → DB 적재."""
    master_id = task_manager.create_task("한국 트렌드 랭킹 수집 (올리브영)", len(CATEGORIES))
    task_manager.start_task(master_id)

    async def _task():
        try:
            page = await browser_manager.get_page()

            def prog(cat, n):
                task_manager.update_progress(master_id, 1, f"{cat}: {n}개")

            rows = await crawl_oliveyoung_rankings(page, top_n=top_n, progress=prog)
            if not rows:
                task_manager.fail_task(master_id, "수집 0건 — 기존 데이터 보존(저장 스킵)")
                return
            saved = await _save_rankings("oliveyoung", rows)
            task_manager.complete_task(master_id, f"올리브영 {saved}건 적재")
        except Exception as e:
            task_manager.fail_task(master_id, str(e))

    asyncio.create_task(_task())
    return {"status": "started", "master_task_id": master_id}


@router.get("/{lookup_date}")
async def get_kr_trend(lookup_date: date, source: str = "oliveyoung"):
    async with async_session() as session:
        result = await session.execute(
            select(KrTrendRanking).where(and_(
                KrTrendRanking.source == source,
                KrTrendRanking.lookup_date == lookup_date,
            )).order_by(KrTrendRanking.category_name, KrTrendRanking.rank)
        )
        rows = result.scalars().all()
    return {
        "lookup_date": str(lookup_date),
        "source": source,
        "count": len(rows),
        "items": [
            {"category": r.category_name, "rank": r.rank, "brand": r.brand,
             "product_name": r.product_name, "price": r.price}
            for r in rows
        ],
    }
