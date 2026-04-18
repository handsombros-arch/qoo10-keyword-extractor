import re
from datetime import date

from app.config import settings
from app.scrapers.base import BaseScraper


class NaverShoppingScraper(BaseScraper):
    """M08: 네이버 쇼핑 상품 검색"""

    async def run(self, keyword: str, **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("네이버 쇼핑 검색", 1)
        self.tasks.start_task(task_id)

        try:
            self.tasks.update_progress(task_id, 0, f"'{keyword}' 네이버 검색 중...")

            url = f"{settings.NAVER_SHOPPING_URL}?query={keyword}"
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # 스크롤
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)

            products = await self._extract_products(page, keyword)

            self.tasks.complete_task(task_id, f"{len(products)}개 상품 수집")
            return {"task_id": task_id, "products": products}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _extract_products(self, page, keyword: str) -> list[dict]:
        products = []

        items = await page.query_selector_all(
            "[class*='product_item'], [class*='basicList_item']"
        )

        for item in items[:30]:
            try:
                product = {"source": "naver", "search_keyword": keyword, "lookup_date": date.today()}

                name_el = await item.query_selector("[class*='title'], [class*='name']")
                if name_el:
                    product["product_name"] = (await name_el.inner_text()).strip()

                price_el = await item.query_selector("[class*='price'] em, [class*='price'] span")
                if price_el:
                    text = await price_el.inner_text()
                    nums = re.sub(r"[^\d]", "", text)
                    product["price_krw"] = int(nums) if nums else 0

                # 배송비
                ship_el = await item.query_selector("[class*='delivery'], [class*='etc']")
                if ship_el:
                    product["shipping_fee"] = (await ship_el.inner_text()).strip()

                img_el = await item.query_selector("img")
                if img_el:
                    product["cover_image_url"] = await img_el.get_attribute("src") or ""

                link_el = await item.query_selector("a[href]")
                if link_el:
                    product["product_url"] = await link_el.get_attribute("href") or ""

                if product.get("product_name"):
                    products.append(product)

            except Exception:
                continue

        return products
