import re
from datetime import date

from app.config import settings
from app.scrapers.base import BaseScraper


class CompetitionScraper(BaseScraper):
    """M03: 경쟁강도 분석 (상품수/검색수, 국가별 상품수)"""

    async def run(self, keywords: list[dict], **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("경쟁강도 분석", len(keywords))
        self.tasks.start_task(task_id)

        results = []

        try:
            for kw in keywords:
                keyword_jp = kw.get("keyword_jp", "")
                search_weekly = kw.get("search_volume_weekly", 0)

                self.tasks.update_progress(
                    task_id, 0, f"'{keyword_jp}' 분석 중..."
                )

                # 이미지 로딩 차단 (속도 향상)
                await page.route("**/*.{png,jpg,jpeg,gif,svg,webp}", lambda route: route.abort())

                search_url = f"{settings.QOO10_SEARCH_URL}?keyword={keyword_jp}"
                await page.goto(search_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # 전체 상품수 추출
                total_products = await self._get_total_products(page)

                # 국가별 상품수
                products_jp, products_kr, products_cn, products_other = await self._get_country_products(page)

                # 경쟁강도 계산
                competition = 0.0
                if search_weekly and search_weekly > 0:
                    competition = round(total_products / search_weekly, 2)

                result = {
                    "keyword_jp": keyword_jp,
                    "lookup_date": date.today(),
                    "competition_intensity": competition,
                    "total_products": total_products,
                    "products_jp": products_jp,
                    "products_kr": products_kr,
                    "products_cn": products_cn,
                    "products_other": products_other,
                    "search_volume_weekly": search_weekly,
                    "search_volume_daily": kw.get("search_volume_daily", 0),
                }
                results.append(result)

                self.tasks.update_progress(
                    task_id, 1,
                    f"'{keyword_jp}' 경쟁강도: {competition} (상품수: {total_products})"
                )

                # 이미지 차단 해제
                await page.unroute("**/*.{png,jpg,jpeg,gif,svg,webp}")

            self.tasks.complete_task(task_id, f"{len(results)}개 키워드 분석 완료")
            return {"task_id": task_id, "results": results}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _get_total_products(self, page) -> int:
        """전체 상품수 추출 (VBA: #items > strong)"""
        try:
            el = await page.query_selector("#items strong, .search-count strong, .result_total strong")
            if el:
                text = await el.inner_text()
                nums = re.sub(r"[^\d]", "", text)
                return int(nums) if nums else 0
        except Exception:
            pass
        return 0

    async def _get_country_products(self, page) -> tuple:
        """국가별 상품수 추출 (VBA: data-nation_code)"""
        jp, kr, cn, other = 0, 0, 0, 0

        try:
            tabs = await page.query_selector_all("[data-nation_code]")
            for tab in tabs:
                nation = await tab.get_attribute("data-nation_code")
                text = await tab.inner_text()
                count = int(re.sub(r"[^\d]", "", text)) if re.search(r"\d", text) else 0

                if nation == "JP":
                    jp = count
                elif nation == "KR":
                    kr = count
                elif nation == "CN":
                    cn = count
                elif nation == "OT":
                    other = count
        except Exception:
            pass

        return jp, kr, cn, other
