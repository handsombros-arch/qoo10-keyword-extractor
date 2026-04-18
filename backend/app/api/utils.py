import io
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_session
from app.db.sqlite_repo import SQLiteKeywordRepository, SQLiteBidRepository, SQLiteProductRepository
from app.services.exchange_rate import get_exchange_rate
from app.services.translation import translate_papago

router = APIRouter(prefix="/api/utils", tags=["utils"])


class TranslateRequest(BaseModel):
    text: str
    source: str = "ko"
    target: str = "ja"


@router.get("/exchange-rate")
async def exchange_rate(currency: str = "JPY"):
    rate = await get_exchange_rate(currency)
    return {"currency": currency, "rate": rate}


@router.post("/translate")
async def translate(req: TranslateRequest):
    result = await translate_papago(req.text, req.source, req.target)
    return {"original": req.text, "translated": result}


@router.get("/export/keywords")
async def export_keywords_csv(session: AsyncSession = Depends(get_session)):
    """키워드 데이터를 CSV로 내보내기"""
    repo = SQLiteKeywordRepository(session)
    keywords = await repo.get_keywords()

    output = io.StringIO()
    output.write('\ufeff')  # BOM for Excel
    headers = ["순위", "키워드(일본어)", "키워드(한국어)", "카테고리", "분류",
               "검색수(주평)", "검색수(전날)", "경쟁강도", "전체상품수",
               "일본", "한국", "중국", "그외", "조회날짜"]
    output.write(",".join(headers) + "\n")

    for kw in keywords:
        row = [
            str(kw.get("rank", "")),
            kw.get("keyword_jp", ""),
            kw.get("keyword_kr", ""),
            kw.get("category", ""),
            kw.get("classification", ""),
            str(kw.get("search_volume_weekly", "")),
            str(kw.get("search_volume_daily", "")),
            str(kw.get("competition_intensity", "")),
            str(kw.get("total_products", "")),
            str(kw.get("products_jp", "")),
            str(kw.get("products_kr", "")),
            str(kw.get("products_cn", "")),
            str(kw.get("products_other", "")),
            str(kw.get("lookup_date", "")),
        ]
        output.write(",".join(row) + "\n")

    output.seek(0)
    filename = f"keywords_{date.today()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export/products")
async def export_products_csv(session: AsyncSession = Depends(get_session)):
    """상품 데이터를 CSV로 내보내기"""
    repo = SQLiteProductRepository(session)
    products = await repo.get_qoo10_products()

    output = io.StringIO()
    output.write('\ufeff')
    headers = ["상품명", "가격(엔)", "배송비", "출하지", "상품URL", "조회날짜"]
    output.write(",".join(headers) + "\n")

    for p in products:
        row = [
            (p.get("product_name", "") or "").replace(",", " "),
            str(p.get("price_jpy", "")),
            (p.get("shipping_fee", "") or "").replace(",", " "),
            p.get("origin", ""),
            p.get("product_url", ""),
            str(p.get("lookup_date", "")),
        ]
        output.write(",".join(row) + "\n")

    output.seek(0)
    filename = f"products_{date.today()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
