"""가격비교 API: 한글 키워드 → 네이버 + 큐텐 병렬 조회 + 환율 적용."""
from fastapi import APIRouter
from pydantic import BaseModel

from app.browser.manager import browser_manager
from app.scrapers.m08_naver import NaverShoppingScraper
from app.scrapers.m09_qoo10_products import Qoo10ProductScraper
from app.services.exchange_rate import get_exchange_rate
from app.services.task_manager import task_manager
from app.services.translation import translate_papago

router = APIRouter(prefix="/api/price-compare", tags=["price-compare"])


class CompareRequest(BaseModel):
    keyword_ko: str
    limit: int = 30


@router.post("/search")
async def compare(req: CompareRequest):
    if not browser_manager.is_logged_in:
        # 로그인 없이도 상품 검색은 가능하지만 브라우저 세션이 살아 있어야 함
        try:
            await browser_manager.get_page()
        except Exception:
            return {"error": "브라우저가 준비되지 않았습니다. 먼저 로그인 페이지에서 크롬 창을 열어주세요."}

    keyword_ko = req.keyword_ko.strip()
    if not keyword_ko:
        return {"error": "키워드를 입력하세요"}

    # 1) 한글 → 일본어 번역
    keyword_ja = await translate_papago(keyword_ko, source="ko", target="ja")

    # 2) JPY → KRW 환율 (1엔당 원화)
    rate_jpy_to_krw = await get_exchange_rate("JPY")
    # dunamu API는 보통 100엔당 원화를 반환 → 1엔 단위로 나누기
    # basePrice 예: 927.98 (100엔당 927.98원)
    per_yen_krw = rate_jpy_to_krw / 100.0 if rate_jpy_to_krw > 20 else rate_jpy_to_krw

    # 3) Qoo10 상품 검색 (일본어 키워드)
    qoo10_scraper = Qoo10ProductScraper(browser_manager, task_manager)
    qoo10_result = await qoo10_scraper.run(keyword=keyword_ko, keyword_jp=keyword_ja)
    qoo10_products = (qoo10_result.get("products") or [])[: req.limit]

    # 엔화 → 원화 환산 추가
    for p in qoo10_products:
        jpy = p.get("price_jpy") or 0
        p["price_krw"] = round(jpy * per_yen_krw) if jpy else 0
        # lookup_date는 date 객체 → 문자열로
        ld = p.get("lookup_date")
        if ld is not None and not isinstance(ld, str):
            p["lookup_date"] = str(ld)

    # 4) 네이버 쇼핑 (한글 키워드)
    naver_scraper = NaverShoppingScraper(browser_manager, task_manager)
    naver_result = await naver_scraper.run(keyword=keyword_ko)
    naver_products = (naver_result.get("products") or [])[: req.limit]
    for p in naver_products:
        ld = p.get("lookup_date")
        if ld is not None and not isinstance(ld, str):
            p["lookup_date"] = str(ld)

    return {
        "keyword_ko": keyword_ko,
        "keyword_ja": keyword_ja,
        "rate_jpy_krw_per_100": rate_jpy_to_krw,
        "rate_per_yen": per_yen_krw,
        "qoo10": qoo10_products,
        "naver": naver_products,
    }
