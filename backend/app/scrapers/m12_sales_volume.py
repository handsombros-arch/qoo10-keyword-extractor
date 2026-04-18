import re
from datetime import date

from app.scrapers.base import BaseScraper


class SalesVolumeScraper(BaseScraper):
    """M12: 판매량 수집"""

    async def run(self, product_urls: list[dict], **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("판매량 수집", len(product_urls))
        self.tasks.start_task(task_id)

        results = []

        try:
            for item in product_urls:
                url = item.get("product_url", "")
                product_name = item.get("product_name", "")

                if not url:
                    continue

                self.tasks.update_progress(task_id, 0, f"'{product_name[:20]}' 판매량 확인 중...")

                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                sales = await self._extract_sales_volume(page)

                results.append({
                    **item,
                    "sales_volume": sales,
                    "lookup_date": date.today(),
                })

                self.tasks.update_progress(task_id, 1, f"'{product_name[:20]}' 판매량: {sales}")

            self.tasks.complete_task(task_id, f"{len(results)}개 상품 판매량 수집 완료")
            return {"task_id": task_id, "results": results}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _extract_sales_volume(self, page) -> int:
        """상품 페이지에서 판매량 추출"""
        try:
            # 여러 셀렉터 시도
            selectors = [
                ".sold_count", "[class*='sold']", "[class*='sales']",
                ".item_count", "[class*='count']",
            ]

            for selector in selectors:
                el = await page.query_selector(selector)
                if el:
                    text = await el.inner_text()
                    nums = re.sub(r"[^\d]", "", text)
                    if nums:
                        return int(nums)

            # 페이지 전체 텍스트에서 판매량 패턴 검색
            content = await page.content()
            match = re.search(r'(?:販売数|sold|판매).*?(\d[\d,]*)', content)
            if match:
                return int(match.group(1).replace(",", ""))

        except Exception:
            pass

        return 0
