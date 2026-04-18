import re
from datetime import date

from app.config import settings
from app.scrapers.base import BaseScraper


class RelatedKeywordScraper(BaseScraper):
    """M05: 연관/유사 키워드 수집"""

    async def run(self, keywords: list[str], **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("연관 키워드 수집", len(keywords))
        self.tasks.start_task(task_id)

        all_results = []

        try:
            url = f"{settings.QOO10_ADPLUS_URL}ADPlusKeyword.aspx"
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)

            for keyword in keywords:
                self.tasks.update_progress(task_id, 0, f"'{keyword}' 연관 키워드 검색 중...")

                # 키워드 입력
                input_el = await page.query_selector("#txt_srch_keyword")
                if input_el:
                    await input_el.fill("")
                    await input_el.fill(keyword)

                # 검색 버튼 클릭
                search_btn = await page.query_selector("#btn_srch_keyword, .btn_search, [onclick*='search']")
                if search_btn:
                    await search_btn.click()
                    await page.wait_for_timeout(2000)

                # 유사 키워드 추출
                similar = await self._extract_similar_keywords(page, keyword)
                all_results.extend(similar)

                # 연관 키워드 추출
                related = await self._extract_related_keywords(page, keyword)
                all_results.extend(related)

                self.tasks.update_progress(
                    task_id, 1,
                    f"'{keyword}' 유사 {len(similar)}개 + 연관 {len(related)}개 수집"
                )

            self.tasks.complete_task(task_id, f"{len(all_results)}개 키워드 수집 완료")
            return {"task_id": task_id, "keywords": all_results}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _extract_similar_keywords(self, page, source_keyword: str) -> list[dict]:
        """유사 키워드 추출 (VBA: #tbody_keyword_infomation)"""
        keywords = []
        try:
            tbody = await page.query_selector("#tbody_keyword_infomation")
            if not tbody:
                return keywords

            rows = await tbody.query_selector_all("tr")
            for row in rows:
                cells = await row.query_selector_all("td, th")
                if len(cells) >= 2:
                    kw_text = (await cells[0].inner_text()).strip()
                    search_text = (await cells[1].inner_text()).strip()
                    search_daily = int(re.sub(r"[^\d]", "", search_text)) if search_text else 0

                    if kw_text:
                        keywords.append({
                            "keyword_jp": kw_text,
                            "lookup_date": date.today(),
                            "classification": "유사",
                            "search_volume_daily": search_daily,
                            "index_key": f"{date.today()}_유사_{kw_text}",
                        })
        except Exception:
            pass
        return keywords

    async def _extract_related_keywords(self, page, source_keyword: str) -> list[dict]:
        """연관 키워드 추출 (VBA: #tbody_related_keyword)"""
        keywords = []
        try:
            tbody = await page.query_selector("#tbody_related_keyword")
            if not tbody:
                return keywords

            rows = await tbody.query_selector_all("tr")
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 3:
                    kw_text = (await cells[0].inner_text()).strip()
                    weekly_text = (await cells[1].inner_text()).strip()
                    daily_text = (await cells[2].inner_text()).strip()

                    search_weekly = int(re.sub(r"[^\d]", "", weekly_text)) if weekly_text else 0
                    search_daily = int(re.sub(r"[^\d]", "", daily_text)) if daily_text else 0

                    if kw_text:
                        keywords.append({
                            "keyword_jp": kw_text,
                            "lookup_date": date.today(),
                            "classification": "연관",
                            "search_volume_weekly": search_weekly,
                            "search_volume_daily": search_daily,
                            "index_key": f"{date.today()}_연관_{kw_text}",
                        })
        except Exception:
            pass
        return keywords
