import asyncio
import traceback

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.db.connection import get_session, async_session
from app.db.sqlite_repo import SQLiteTrackingRepository
from app.schemas.tracking import TrackingItemCreate
from app.scrapers.m10_ranking_tracker import RankingTrackerScraper
from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/tracking", tags=["tracking"])


@router.get("/items")
async def get_tracking_items(session: AsyncSession = Depends(get_session)):
    repo = SQLiteTrackingRepository(session)
    return await repo.get_tracking_items()


@router.post("/items")
async def add_tracking_item(req: TrackingItemCreate, session: AsyncSession = Depends(get_session)):
    repo = SQLiteTrackingRepository(session)
    item_id = await repo.save_tracking_item(req.model_dump())
    return {"id": item_id, "status": "created"}


@router.get("/items/{item_id}/history")
async def get_tracking_history(item_id: int, session: AsyncSession = Depends(get_session)):
    repo = SQLiteTrackingRepository(session)
    return await repo.get_tracking_history(item_id)


@router.post("/run")
async def run_tracking(session: AsyncSession = Depends(get_session)):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    repo = SQLiteTrackingRepository(session)
    items = await repo.get_tracking_items()
    if not items:
        return {"error": "추적할 항목이 없습니다."}

    async def _task():
        try:
            scraper = RankingTrackerScraper(browser_manager, task_manager)
            result = await scraper.run(items=items)
            if "results" in result:
                async with async_session() as session2:
                    repo2 = SQLiteTrackingRepository(session2)
                    await repo2.save_tracking_history(result["results"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started", "count": len(items)}
