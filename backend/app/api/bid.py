import asyncio
import traceback

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.db.connection import get_session, async_session
from app.db.sqlite_repo import SQLiteBidRepository
from app.schemas.bid import BidCollectRequest
from app.scrapers.m04_bid_results import BidResultScraper
from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/bid", tags=["bid"])


@router.get("/history")
async def get_bid_history(keyword: str = None, session: AsyncSession = Depends(get_session)):
    repo = SQLiteBidRepository(session)
    return await repo.get_bid_history(keyword)


@router.post("/collect")
async def collect_bid_results(req: BidCollectRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    async def _task():
        try:
            scraper = BidResultScraper(browser_manager, task_manager)
            result = await scraper.run(keywords=req.keywords)
            if "results" in result:
                async with async_session() as session:
                    repo = SQLiteBidRepository(session)
                    await repo.save_bid_history(result["results"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started"}
