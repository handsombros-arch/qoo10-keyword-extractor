import re
from datetime import date

from app.scrapers.base import BaseScraper


class RankingTrackerScraper(BaseScraper):
    """M10: 검색 노출 순위 추적"""

    async def run(self, items: list[dict], **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("순위 추적", len(items))
        self.tasks.start_task(task_id)

        results = []

        try:
            for item in items:
                product_id = item.get("product_id", "")
                keyword = item.get("keyword", "")
                tracking_item_id = item.get("id", 0)

                self.tasks.update_progress(task_id, 0, f"'{keyword}' 순위 확인 중...")

                search_url = f"https://www.qoo10.jp/s/{keyword}"
                await page.goto(search_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                rank = await self._find_product_rank(page, product_id)

                results.append({
                    "tracking_item_id": tracking_item_id,
                    "lookup_date": date.today(),
                    "rank_position": rank,
                })

                rank_display = f"{rank}위" if rank > 0 else "100위 이상"
                self.tasks.update_progress(task_id, 1, f"'{keyword}' → {rank_display}")

            self.tasks.complete_task(task_id, f"{len(results)}개 항목 순위 추적 완료")
            return {"task_id": task_id, "results": results}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _find_product_rank(self, page, product_id: str, max_rank: int = 100) -> int:
        """상품 순위 찾기 (최대 100위까지 스크롤)"""
        rank = 0

        for scroll in range(10):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)

            # 상품번호로 매칭
            items = await page.query_selector_all(
                f'[data-item-no="{product_id}"], '
                f'a[href*="/g/{product_id}"], '
                f'a[href*="/{product_id}"]'
            )

            if items:
                # 전체 상품 목록에서 위치 찾기
                all_items = await page.query_selector_all(".s_item_group .s_item, .goods_list li")
                for i, el in enumerate(all_items):
                    html = await el.inner_html()
                    if product_id in html:
                        rank = i + 1
                        return rank

            if rank > max_rank:
                break

        return 0  # 0 = 미발견
