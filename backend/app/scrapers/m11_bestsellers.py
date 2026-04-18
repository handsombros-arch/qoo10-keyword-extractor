import re
from datetime import date

from app.config import settings
from app.scrapers.base import BaseScraper

CATEGORY_CODES = {
    0: ("종합", 0),
    1: ("여성패션", 1),
    2: ("뷰티&화장품", 2),
    3: ("남성&스포츠", 3),
    4: ("디지털", 4),
    5: ("홈&생활", 5),
    6: ("식품", 6),
    7: ("엔터테인먼트", 10),
    8: ("베이비&키즈", 13),
    9: ("모바일", 14),
    10: ("K-POP", 10),
    11: ("펫 푸드&용품", 15),
}


class BestsellerScraper(BaseScraper):
    """M11: 인기상품 랭킹 수집"""

    async def run(self, category: int = 0, **params) -> dict:
        page = await self.browser.get_page()
        cat_name, cat_code = CATEGORY_CODES.get(category, ("종합", 0))

        task_id = self.tasks.create_task(f"인기상품 ({cat_name})", 50)
        self.tasks.start_task(task_id)

        try:
            url = f"{settings.QOO10_BESTSELLER_URL}?g={cat_code}"
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            # 스크롤하여 더 로드
            for _ in range(5):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)

            items = await self._extract_items(page, cat_name, task_id)

            self.tasks.complete_task(task_id, f"{len(items)}개 인기상품 수집 완료")
            return {"task_id": task_id, "items": items}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _extract_items(self, page, category: str, task_id: str) -> list[dict]:
        items = []

        product_els = await page.query_selector_all(
            ".best_list li, .ranking_list li, [class*='rank-item'], [class*='product']"
        )

        for i, el in enumerate(product_els[:100]):
            try:
                item = {"category": category, "rank": i + 1, "lookup_date": date.today()}

                name_el = await el.query_selector("a[title], .tit, [class*='name']")
                if name_el:
                    item["product_name"] = (await name_el.inner_text()).strip()

                price_el = await el.query_selector(".prc strong, .price, [class*='price']")
                if price_el:
                    text = await price_el.inner_text()
                    nums = re.sub(r"[^\d]", "", text)
                    item["price_jpy"] = int(nums) if nums else 0

                brand_el = await el.query_selector(".brand, [class*='brand']")
                if brand_el:
                    item["brand"] = (await brand_el.inner_text()).strip()

                img_el = await el.query_selector("img")
                if img_el:
                    item["cover_image_url"] = await img_el.get_attribute("src") or ""

                link_el = await el.query_selector("a[href]")
                if link_el:
                    href = await link_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = f"https://www.qoo10.jp{href}"
                    item["product_url"] = href

                if item.get("product_name"):
                    items.append(item)
                    self.tasks.update_progress(task_id, 1, f"{i+1}위: {item['product_name'][:30]}")

            except Exception:
                continue

        return items
