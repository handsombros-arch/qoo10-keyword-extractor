import asyncio
import traceback

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.db.connection import get_session, async_session
from app.db.sqlite_repo import SQLiteBestsellerRepository
from app.scrapers.m11_bestsellers import BestsellerScraper
from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/bestsellers", tags=["bestsellers"])


@router.get("")
async def get_bestsellers(category: str = None, session: AsyncSession = Depends(get_session)):
    repo = SQLiteBestsellerRepository(session)
    return await repo.get_bestseller_items(category)


@router.post("/collect")
async def collect_bestsellers(category: int = 0):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    async def _task():
        try:
            scraper = BestsellerScraper(browser_manager, task_manager)
            result = await scraper.run(category=category)
            if "items" in result:
                async with async_session() as session:
                    repo = SQLiteBestsellerRepository(session)
                    await repo.save_bestseller_items(result["items"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started"}
