import re
from datetime import date

from app.config import settings
from app.scrapers.base import BaseScraper


class Qoo10ProductScraper(BaseScraper):
    """M09: Qoo10 상품 검색"""

    async def run(self, keyword: str, keyword_jp: str = None, **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("Qoo10 상품 검색", 1)
        self.tasks.start_task(task_id)

        try:
            search_kw = keyword_jp or keyword
            self.tasks.update_progress(task_id, 0, f"'{search_kw}' 검색 중...")

            search_url = f"https://www.qoo10.jp/s/{search_kw}"
            await page.goto(search_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            # 스크롤하여 더 많은 상품 로드
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)

            products = await self._extract_products(page, keyword)

            self.tasks.complete_task(task_id, f"{len(products)}개 상품 수집 완료")
            return {"task_id": task_id, "products": products}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _extract_products(self, page, keyword: str) -> list[dict]:
        """상품 정보 추출"""
        products = []

        try:
            # 상품 리스트 요소 찾기
            items = await page.query_selector_all(".s_item_group .s_item, .sc-dkrFOg, [class*='product-item']")

            if not items:
                items = await page.query_selector_all(".s_item_group li, .goods_list li")

            for item in items[:50]:  # 최대 50개
                try:
                    product = {}

                    # 상품명
                    name_el = await item.query_selector("a[title], .sbj a, .tit, [class*='name']")
                    if name_el:
                        product["product_name"] = (await name_el.inner_text()).strip()

                    # 가격
                    price_el = await item.query_selector(".prc strong, .price, [class*='price']")
                    if price_el:
                        price_text = await price_el.inner_text()
                        nums = re.sub(r"[^\d]", "", price_text)
                        product["price_jpy"] = int(nums) if nums else 0

                    # 배송비
                    ship_el = await item.query_selector(".ship, [class*='shipping'], [class*='delivery']")
                    if ship_el:
                        product["shipping_fee"] = (await ship_el.inner_text()).strip()
                    else:
                        product["shipping_fee"] = ""

                    # 출하지
                    origin_el = await item.query_selector(".national, [class*='origin'], [class*='country']")
                    if origin_el:
                        product["origin"] = (await origin_el.inner_text()).strip()
                    else:
                        product["origin"] = ""

                    # 이미지
                    img_el = await item.query_selector("img")
                    if img_el:
                        src = await img_el.get_attribute("src") or await img_el.get_attribute("data-src") or ""
                        product["cover_image_url"] = src

                    # 링크
                    link_el = await item.query_selector("a[href]")
                    if link_el:
                        href = await link_el.get_attribute("href") or ""
                        if href and not href.startswith("http"):
                            href = f"https://www.qoo10.jp{href}"
                        product["product_url"] = href

                    product["search_keyword"] = keyword
                    product["lookup_date"] = date.today()

                    if product.get("product_name"):
                        products.append(product)

                except Exception:
                    continue

        except Exception:
            pass

        return products
