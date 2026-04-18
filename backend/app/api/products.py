import asyncio
import traceback

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.db.connection import get_session, async_session
from app.db.sqlite_repo import SQLiteProductRepository
from app.schemas.product import ProductSearchRequest
from app.scrapers.m07_coupang import CoupangScraper
from app.scrapers.m08_naver import NaverShoppingScraper
from app.scrapers.m09_qoo10_products import Qoo10ProductScraper
from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("/qoo10")
async def get_qoo10_products(keyword: str = None, session: AsyncSession = Depends(get_session)):
    repo = SQLiteProductRepository(session)
    return await repo.get_qoo10_products(keyword)


@router.get("/domestic")
async def get_domestic_products(source: str = None, session: AsyncSession = Depends(get_session)):
    repo = SQLiteProductRepository(session)
    return await repo.get_domestic_products(source)


@router.post("/qoo10")
async def search_qoo10_products(req: ProductSearchRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    async def _task():
        try:
            scraper = Qoo10ProductScraper(browser_manager, task_manager)
            result = await scraper.run(keyword=req.keyword)
            if "products" in result:
                async with async_session() as session:
                    repo = SQLiteProductRepository(session)
                    await repo.save_qoo10_products(result["products"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started"}


@router.post("/coupang")
async def search_coupang_products(req: ProductSearchRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    async def _task():
        try:
            scraper = CoupangScraper(browser_manager, task_manager)
            result = await scraper.run(keyword=req.keyword)
            if "products" in result:
                async with async_session() as session:
                    repo = SQLiteProductRepository(session)
                    await repo.save_domestic_products(result["products"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started"}


@router.post("/naver")
async def search_naver_products(req: ProductSearchRequest):
    if not browser_manager.is_logged_in:
        return {"error": "로그인이 필요합니다."}

    async def _task():
        try:
            scraper = NaverShoppingScraper(browser_manager, task_manager)
            result = await scraper.run(keyword=req.keyword)
            if "products" in result:
                async with async_session() as session:
                    repo = SQLiteProductRepository(session)
                    await repo.save_domestic_products(result["products"])
        except Exception:
            traceback.print_exc()

    asyncio.create_task(_task())
    return {"status": "started"}
