import re
import traceback
from datetime import date
from urllib.parse import unquote

from app.config import settings
from app.scrapers.base import BaseScraper

CATEGORIES = {
    1: "01.종합",
    2: "02.여성패션",
    3: "03.뷰티&화장품",
    4: "04.남성&스포츠",
    5: "05.디지털",
    6: "06.홈&생활",
    7: "07.식품",
    8: "08.엔터테인먼트&e티켓",
    9: "09.베이비&키즈",
    10: "10.모바일",
    11: "11.펫 푸드&용품",
    12: "12.서플리먼트&다이어트",
}


class TrendKeywordScraper(BaseScraper):
    """M02: 인기/트렌드 키워드 추출"""

    async def run(self, category: int = 1, types: list[str] = None, **params) -> dict:
        if types is None:
            types = ["popular", "daily", "weekly"]

        page = await self.browser.get_page()
        url = f"{settings.QOO10_ADPLUS_URL}PopADPlusPopularKeyword.aspx?plus_type=KW"

        total = 0
        if "popular" in types:
            total += 100 if category == 1 else 30
        if "daily" in types:
            total += 10
        if "weekly" in types:
            total += 10

        task_id = self.tasks.create_task("인기 키워드 가져오기", total)
        self.tasks.start_task(task_id)

        try:
            print(f"[M02] 트렌드 페이지 이동: {url}")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(3000)

            # AJAX 데이터 로드 대기
            try:
                await page.wait_for_selector(
                    "#tbody_popular_list tr", state="attached", timeout=15000
                )
            except Exception:
                await page.wait_for_timeout(5000)

            # 카테고리 선택
            category_name = CATEGORIES.get(category, "01.종합")
            select_el = await page.query_selector("#GROUP_CODE_PopAdplus")
            if select_el:
                options = await select_el.query_selector_all("option")
                if category <= len(options):
                    value = await options[category - 1].get_attribute("value")
                    if value is not None:
                        await select_el.select_option(value=value)
                    else:
                        await select_el.select_option(index=category - 1)
                    await page.wait_for_timeout(3000)

            self.tasks.update_progress(task_id, 0, f"'{category_name}' 키워드 수집 시작")
            all_keywords = []

            if "popular" in types:
                keywords = await self._extract_keywords(
                    page, "tbody_popular_list", category_name, "1.주요", task_id
                )
                print(f"[M02] 주요 키워드: {len(keywords)}개")
                all_keywords.extend(keywords)

            if "daily" in types:
                keywords = await self._extract_keywords(
                    page, "tbody_daily_list", category_name, "2.일간", task_id
                )
                print(f"[M02] 일간 키워드: {len(keywords)}개")
                all_keywords.extend(keywords)

            if "weekly" in types:
                keywords = await self._extract_keywords(
                    page, "tbody_weekly_list", category_name, "3.주간", task_id
                )
                print(f"[M02] 주간 키워드: {len(keywords)}개")
                all_keywords.extend(keywords)

            msg = f"{len(all_keywords)}개 키워드 수집 완료"
            print(f"[M02] {msg}")
            self.tasks.complete_task(task_id, msg)
            return {"task_id": task_id, "keywords": all_keywords}

        except Exception as e:
            print(f"[M02] 오류: {e}")
            traceback.print_exc()
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _extract_keywords(
        self, page, table_id: str, category: str, classification: str, task_id: str
    ) -> list[dict]:
        """
        HTML 구조 (실제 확인됨):
        <tr id="tr_0" all_yn="Y">
          <td><p class="rank all">1</p></td>
          <td>カーテン (4)<table ...>...</table></td>
          <td>24,365 </td>
          <td>19,619</td>
          <td>18</td>
          <td>22,900 ~ 2,000</td>
        </tr>
        """
        keywords = []

        tbody = await page.query_selector(f"#{table_id}")
        if not tbody:
            print(f"[M02] #{table_id} 못 찾음")
            return keywords

        # all_yn='Y'인 행 (VBA와 동일)
        rows = await tbody.query_selector_all("tr[all_yn='Y']")
        if not rows:
            rows = await tbody.query_selector_all("tr[id^='tr_']")

        print(f"[M02] #{table_id}: {len(rows)}개 행")

        for row in rows:
            try:
                tds = await row.query_selector_all(":scope > td")
                if len(tds) < 4:
                    continue

                # 1. 순위: <td><p class="rank all">1</p></td>
                rank_el = await tds[0].query_selector("p.rank.all, p.rank")
                if not rank_el:
                    rank_text = await tds[0].text_content()
                else:
                    rank_text = await rank_el.text_content()
                rank_clean = re.sub(r"\D", "", rank_text.strip())
                if not rank_clean:
                    continue
                rank = int(rank_clean)

                # 2. 키워드: <td>キーワード名 (N)<table>...</table></td>
                # TD 내부 table을 JS로 제거한 뒤 순수 텍스트만 추출 (replace 방식은 부분매칭으로 불안정)
                kw_td = tds[1]
                kw_text_raw = await kw_td.evaluate(
                    "el => { const c = el.cloneNode(true); "
                    "c.querySelectorAll('table').forEach(t => t.remove()); "
                    "return (c.textContent || '').trim(); }"
                )

                # "키워드명 (연관수)" 파싱
                match = re.match(r"^(.+?)\s*\((\d+)\)\s*$", kw_text_raw)
                keyword = match.group(1).strip() if match else kw_text_raw.strip()

                if "%" in keyword:
                    try:
                        keyword = unquote(keyword)
                    except Exception:
                        pass

                # 유효성: 빈값, 괄호숫자, 순수숫자는 비정상 행
                if (not keyword
                        or re.fullmatch(r"\(\s*\d+\s*\)", keyword)
                        or re.fullmatch(r"\d+", keyword)):
                    print(f"[M02] 비정상 키워드 skip: rank={rank}, raw={kw_text_raw!r}")
                    continue

                # 3. 검색수(주평): <td>24,365 </td>
                weekly_text = (await tds[2].text_content()).strip().replace(",", "")
                search_weekly = int(weekly_text) if weekly_text.isdigit() else 0

                # 4. 검색수(전날): <td>19,619</td>
                daily_text = (await tds[3].text_content()).strip().replace(",", "")
                search_daily = int(daily_text) if daily_text.isdigit() else 0

                keywords.append({
                    "keyword_jp": keyword,
                    "lookup_date": date.today(),
                    "category": category,
                    "classification": classification,
                    "rank": rank,
                    "search_volume_weekly": search_weekly,
                    "search_volume_daily": search_daily,
                    "index_key": f"{date.today()}_{category}_{classification}_{rank}",
                })

                self.tasks.update_progress(
                    task_id, 1,
                    f"{category} {classification}: {keyword}"
                )

            except Exception as e:
                print(f"[M02] 행 파싱 오류: {e}")
                continue

        return keywords
