import asyncio
import traceback
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import browser_manager
from app.db.connection import get_session, async_session
from app.db.sqlite_repo import SQLiteProductRepository
from app.schemas.product import ProductSearchRequest
from app.scrapers.m07_coupang import CoupangScraper
from app.scrapers.m08_naver import NaverShoppingScraper
from app.scrapers.m09_qoo10_products import Qoo10ProductScraper
from app.services.qoo10_export import build_qoo10_excel
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


class Qoo10ExportRow(BaseModel):
    product_name: str = ""
    product_name_ko: str = ""
    sell_price_jpy: float = 0
    cover_image_url: str = ""
    weight_g: float = 0
    notes: str = ""
    source: str = ""
    search_keyword: str = ""


class Qoo10ExportDefaults(BaseModel):
    category_number: str = ""
    brand_number: str = ""
    shipping_number: str = ""
    end_date: str = ""        # YYYY-MM-DD
    quantity: int = 100
    available_shipping_date: int = 7
    item_condition_type: str = "1"  # 1=새상품
    origin_type: str = "2"          # 2=해외
    origin_country_id: str = "KR"
    item_status: str = "Y"
    under18s_display: str = "N"
    default_description: str = ""


class Qoo10ExportRequest(BaseModel):
    rows: list[Qoo10ExportRow]
    defaults: Qoo10ExportDefaults


@router.post("/export-qoo10")
async def export_qoo10(req: Qoo10ExportRequest):
    """큐텐 대량등록 엑셀 양식(Qoo10_EditItemList.xlsx)에 맞춰 채운 xlsx 반환."""
    rows_data = [r.dict() for r in req.rows]
    defaults_data = req.defaults.dict()
    xlsx_bytes = build_qoo10_excel(rows_data, defaults_data)

    filename = f"Qoo10_EditItemList_{date.today()}.xlsx"
    return StreamingResponse(
        iter([xlsx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
