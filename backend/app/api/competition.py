import asyncio
import traceback

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.db.connection import get_session, async_session
from app.db.sqlite_repo import SQLiteKeywordRepository
from app.schemas.keyword import CompetitionRequest
from app.scrapers.m03_competition import CompetitionScraper
from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/competition", tags=["competition"])


@router.post("/analyze")
async def analyze_competition(req: CompetitionRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    keywords = [{"keyword_jp": kw, "search_volume_weekly": 0} for kw in req.keywords]

    async def _task():
        try:
            scraper = CompetitionScraper(browser_manager, task_manager)
            result = await scraper.run(keywords=keywords)
            if "results" in result:
                async with async_session() as session:
                    repo = SQLiteKeywordRepository(session)
                    await repo.save_volume_history(result["results"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started"}
