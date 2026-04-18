import re
from datetime import date

from app.config import settings
from app.scrapers.base import BaseScraper


class CoupangScraper(BaseScraper):
    """M07: 쿠팡 상품 검색"""

    async def run(self, keyword: str, **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("쿠팡 상품 검색", 1)
        self.tasks.start_task(task_id)

        try:
            self.tasks.update_progress(task_id, 0, f"'{keyword}' 쿠팡 검색 중...")

            url = f"{settings.COUPANG_SEARCH_URL}?component=&q={keyword}&channel=user"
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # 스크롤
            for _ in range(2):
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

        items = await page.query_selector_all(".search-product, li.search-product")

        for item in items[:30]:
            try:
                product = {"source": "coupang", "search_keyword": keyword, "lookup_date": date.today()}

                name_el = await item.query_selector(".name, .descriptions-inner")
                if name_el:
                    product["product_name"] = (await name_el.inner_text()).strip()

                price_el = await item.query_selector(".price-value, strong.price-value")
                if price_el:
                    text = await price_el.inner_text()
                    nums = re.sub(r"[^\d]", "", text)
                    product["price_krw"] = int(nums) if nums else 0

                # 배송 정보
                badge_el = await item.query_selector(".badge, .delivery-badge")
                if badge_el:
                    product["shipping_fee"] = (await badge_el.inner_text()).strip()

                img_el = await item.query_selector("img")
                if img_el:
                    product["cover_image_url"] = await img_el.get_attribute("src") or ""

                link_el = await item.query_selector("a[href]")
                if link_el:
                    href = await link_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = f"https://www.coupang.com{href}"
                    product["product_url"] = href

                if product.get("product_name"):
                    products.append(product)

            except Exception:
                continue

        return products
