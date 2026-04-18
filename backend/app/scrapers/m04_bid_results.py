import re
from datetime import date

from app.config import settings
from app.scrapers.base import BaseScraper


class BidResultScraper(BaseScraper):
    """M04: 경매 낙찰결과 수집"""

    async def run(self, keywords: list[str], **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("경매 결과 수집", len(keywords))
        self.tasks.start_task(task_id)

        results = []

        try:
            url = f"{settings.QOO10_ADPLUS_URL}ADPlusKeyword.aspx"
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)

            for keyword in keywords:
                self.tasks.update_progress(task_id, 0, f"'{keyword}' 경매 결과 조회 중...")

                # 키워드 입력 및 검색
                input_el = await page.query_selector("#txt_srch_keyword")
                if input_el:
                    await input_el.fill("")
                    await input_el.fill(keyword)

                search_btn = await page.query_selector("#btn_srch_keyword, .btn_search")
                if search_btn:
                    await search_btn.click()
                    await page.wait_for_timeout(2000)

                # 낙찰 결과 추출
                bid_data = await self._extract_bid_data(page, keyword)
                if bid_data:
                    results.append(bid_data)

                self.tasks.update_progress(task_id, 1, f"'{keyword}' 경매 결과 수집 완료")

            self.tasks.complete_task(task_id, f"{len(results)}개 키워드 경매 결과 수집 완료")
            return {"task_id": task_id, "results": results}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _extract_bid_data(self, page, keyword: str) -> dict:
        """낙찰 결과 추출 (VBA: #tbody_winner_list)"""
        try:
            tbody = await page.query_selector("#tbody_winner_list")
            if not tbody:
                return {}

            rows = await tbody.query_selector_all("tr")
            prices = []

            for row in rows:
                cells = await row.query_selector_all("td")
                for cell in cells:
                    text = (await cell.inner_text()).strip()
                    nums = re.sub(r"[^\d]", "", text)
                    if nums:
                        prices.append(int(nums))

            # 10개 미만이면 0으로 채움
            while len(prices) < 10:
                prices.append(0)

            # 검색수 정보
            search_weekly = 0
            search_daily = 0
            bid_count = len([p for p in prices if p > 0])

            # 검색수 추출 시도
            try:
                search_els = await page.query_selector_all(".search-volume, .keyword-info td")
                for el in search_els:
                    text = (await el.inner_text()).strip()
                    nums = re.sub(r"[^\d]", "", text)
                    if nums:
                        if search_weekly == 0:
                            search_weekly = int(nums)
                        elif search_daily == 0:
                            search_daily = int(nums)
            except Exception:
                pass

            return {
                "keyword_jp": keyword,
                "lookup_date": date.today(),
                "index_key": f"{date.today()}_{keyword}",
                "bid_count": bid_count,
                "search_volume_weekly": search_weekly,
                "search_volume_daily": search_daily,
                "bid_price_1": prices[0],
                "bid_price_2": prices[1],
                "bid_price_3": prices[2],
                "bid_price_4": prices[3],
                "bid_price_5": prices[4],
                "bid_price_6": prices[5],
                "bid_price_7": prices[6],
                "bid_price_8": prices[7],
                "bid_price_9": prices[8],
                "bid_price_10": prices[9],
            }
        except Exception:
            return {}
