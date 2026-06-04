"""올리브영 카테고리별 판매 랭킹 크롤러 (R-9, 2026-06-04).

httpx 는 AKAMAI 403 → Playwright headful(실 Chrome)로 우회.
메인(main.do) 먼저 방문해 AKAMAI 쿠키 확보 → getBestList.do 호출:
  dispCatNo=900000100100001 (판매 랭킹 고정) + fltDispCatNo={카테고리} + rowsPerPage=N
파싱: ul.cate_prd_list > li → .tx_brand / .tx_name / .tx_cur .tx_num
"""
import re
from datetime import date

RANKING_DISP_CAT = "900000100100001"  # 판매 랭킹
BASE = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
MAIN = "https://www.oliveyoung.co.kr/store/main/main.do"

# 올리브영 메인 카테고리 (fltDispCatNo, 이름) — 랭킹 페이지 data-ref-dispcatno 11자리 top-level (6/4 검증)
CATEGORIES = [
    ("10000010001", "스킨케어"),
    ("10000010009", "마스크팩"),
    ("10000010010", "클렌징"),
    ("10000010011", "선케어"),
    ("10000010002", "메이크업"),
    ("10000010006", "뷰티소품"),
    ("10000010008", "더모 코스메틱"),
    ("10000010012", "네일"),
    ("10000010004", "헤어케어"),
    ("10000010003", "바디케어"),
    ("10000010005", "향수/디퓨저"),
    ("10000010007", "맨즈에딧"),
    ("10000020001", "건강식품"),
    ("10000020002", "푸드"),
    ("10000020005", "헬스/건강용품"),
    ("10000020003", "구강용품"),
    ("10000020004", "위생용품"),
    ("10000030007", "패션"),
    ("10000030005", "홈리빙/가전"),
    ("10000030006", "취미/팬시"),
]


def _to_int(s: str):
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


async def _parse_top(page, top_n: int):
    items = await page.query_selector_all("ul.cate_prd_list > li")
    out = []
    rank = 0
    for li in items:
        if rank >= top_n:
            break
        name_el = await li.query_selector(".tx_name")
        if not name_el:
            continue
        name = (await name_el.inner_text()).strip()
        if not name:
            continue
        rank += 1
        brand_el = await li.query_selector(".tx_brand")
        price_el = await li.query_selector(".tx_cur .tx_num")
        brand = (await brand_el.inner_text()).strip() if brand_el else ""
        price_text = (await price_el.inner_text()).strip() if price_el else ""
        out.append({
            "rank": rank,
            "brand": brand,
            "product_name": name,
            "price": _to_int(price_text),
            "price_text": price_text,
        })
    return out


async def crawl_oliveyoung_rankings(page, top_n: int = 30, progress=None) -> list:
    """전 메인 카테고리 판매랭킹 top_n 크롤. dict 리스트 반환 (저장은 호출측 책임)."""
    today = date.today()
    results = []
    # AKAMAI 쿠키 확보용 메인 방문
    try:
        await page.goto(MAIN, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(1500)
    except Exception:
        pass
    for flt, cat_name in CATEGORIES:
        url = f"{BASE}?dispCatNo={RANKING_DISP_CAT}&fltDispCatNo={flt}&pageIdx=1&rowsPerPage={top_n}"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(1500)
            rows = await _parse_top(page, top_n)
        except Exception as e:
            print(f"[oliveyoung] {cat_name} ERROR: {e}")
            rows = []
        for r in rows:
            results.append({
                "source": "oliveyoung",
                "category_code": flt,
                "category_name": cat_name,
                "lookup_date": today,
                **r,
            })
        print(f"[oliveyoung] {cat_name}: {len(rows)}개")
        if progress:
            try:
                progress(cat_name, len(rows))
            except Exception:
                pass
    return results
