import os
import re
from datetime import date, datetime

from app.config import settings
from app.scrapers.base import BaseScraper

_DEBUG_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "m04_debug.log")


def _m04_log(msg: str) -> None:
    """print + append to debug file (사후 진단용)."""
    line = f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
    print(line)
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class BidResultScraper(BaseScraper):
    """M04: 경매 낙찰결과 수집.

    VBA(module_28_M04)에 준해 구현:
    - URL: ADPlusKeyword.aspx
    - 검색 버튼: XPath //*[@id='content']/div[4]/div[2]/div/fieldset/a[1]
    - 낙찰 목록: #tbody_winner_list 내부 .topbar 요소 (실제 낙찰자)
    - 각 topbar의 텍스트는 "<rank> <price>" 형태 (공백/개행 구분)
    """

    async def run(self, keywords: list[str], **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("경매 결과 수집", len(keywords))
        self.tasks.start_task(task_id)

        results = []

        try:
            url = f"{settings.QOO10_ADPLUS_URL}ADPlusKeyword.aspx"
            _m04_log(f"[M04] 페이지 이동: {url}")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(1500)

            # 최초 1회: 페이지 구조 진단 (버튼/입력/목록 셀렉터 실측)
            await self._log_page_structure(page, task_id)

            for idx, keyword in enumerate(keywords, 1):
                self.tasks.update_progress(task_id, 0, f"[{idx}/{len(keywords)}] '{keyword}' 조회 중...")

                try:
                    bid_data = await self._query_keyword(page, keyword, idx == 1)
                    if bid_data:
                        results.append(bid_data)
                        _m04_log(
                            f"[M04] '{keyword}' bid_count={bid_data.get('bid_count')} "
                            f"prices={[bid_data.get(f'bid_price_{i}') for i in range(1, 11)]}"
                        )
                except Exception as e:
                    _m04_log(f"[M04] '{keyword}' 조회 실패: {e}")

                self.tasks.update_progress(task_id, 1, f"[{idx}/{len(keywords)}] '{keyword}' 완료")

            self.tasks.complete_task(task_id, f"{len(results)}개 키워드 경매 결과 수집 완료")
            return {"task_id": task_id, "results": results}

        except Exception as e:
            _m04_log(f"[M04] 오류: {e}")
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _log_page_structure(self, page, task_id) -> None:
        """최초 진단: input/button/tbody 구조 + 핸들러 이름 로그."""
        try:
            info = await page.evaluate(
                "() => { "
                "const input = document.getElementById('txt_srch_keyword'); "
                "const btnId = document.getElementById('btn_srch_keyword'); "
                "const btnVbaXp = document.evaluate(\"//*[@id='content']/div[4]/div[2]/div/fieldset/a[1]\", "
                "  document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; "
                "const anchors = Array.from(document.querySelectorAll('#content fieldset a')).slice(0, 5).map(a => ({ "
                "  text: (a.textContent||'').trim().slice(0,20), href: a.getAttribute('href'), onclick: a.getAttribute('onclick') "
                "})); "
                "const tbody = document.getElementById('tbody_winner_list'); "
                "const topbars = tbody ? tbody.querySelectorAll('.topbar').length : 0; "
                "const allTrs = tbody ? tbody.querySelectorAll('tr').length : 0; "
                "const searchFns = Object.keys(window).filter(k => /Search|Winner|Bid|Srch/i.test(k)).slice(0, 20); "
                "return { "
                "  inputExists: !!input, inputValue: input?.value, "
                "  btnIdExists: !!btnId, btnIdAttrs: btnId ? {id:btnId.id, tag:btnId.tagName, onclick:btnId.getAttribute('onclick')} : null, "
                "  btnVbaXpExists: !!btnVbaXp, btnVbaXpAttrs: btnVbaXp ? {tag:btnVbaXp.tagName, text:(btnVbaXp.textContent||'').trim().slice(0,30), onclick:btnVbaXp.getAttribute('onclick'), href:btnVbaXp.getAttribute('href')} : null, "
                "  anchors, tbodyExists: !!tbody, topbars, allTrs, searchFns "
                "}; }"
            )
            _m04_log(f"[M04][DEBUG] 페이지 구조: {info}")
            self.tasks.update_progress(task_id, 0, f"[DEBUG] {info}")
        except Exception as e:
            _m04_log(f"[M04][DEBUG] 구조 조사 실패: {e}")

    async def _query_keyword(self, page, keyword: str, first: bool) -> dict:
        """키워드 하나에 대해 검색 트리거 + tbody_winner_list 파싱."""
        # 1) 키워드 입력
        try:
            await page.fill("#txt_srch_keyword", "")
            await page.fill("#txt_srch_keyword", keyword)
        except Exception as e:
            _m04_log(f"[M04] 입력 실패: {e}")
            return {}

        # 2) 이전 결과 초기화 (첫 행 텍스트 캡처 → 변화 감지)
        before = await page.evaluate(
            "() => { const t = document.getElementById('tbody_winner_list'); "
            "return t ? (t.textContent || '').trim().slice(0, 200) : ''; }"
        )

        # 3) 검색 트리거 — 기법 A: VBA XPath 링크 클릭
        clicked = False
        try:
            link = await page.query_selector("xpath=//*[@id='content']/div[4]/div[2]/div/fieldset/a[1]")
            if link:
                await link.click()
                clicked = True
                if first:
                    _m04_log("[M04] 기법 A (VBA XPath) 클릭 성공")
        except Exception as e:
            if first:
                _m04_log(f"[M04] 기법 A 실패: {e}")

        # 기법 B: onclick/href JS 실행 (anchor 종종 javascript:)
        if not clicked:
            try:
                ran = await page.evaluate(
                    "() => { const link = document.evaluate(\"//*[@id='content']/div[4]/div[2]/div/fieldset/a[1]\", "
                    "document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; "
                    "if (!link) return 'no-link'; "
                    "const oc = link.getAttribute('onclick'); "
                    "if (oc) { try { (new Function(oc)).call(link); return 'onclick-ran'; } catch(e) { return 'onclick-err:'+e.message; } } "
                    "const href = link.getAttribute('href'); "
                    "if (href && href.startsWith('javascript:')) { try { eval(href.slice(11)); return 'href-ran'; } catch(e) { return 'href-err:'+e.message; } } "
                    "link.click(); return 'plain-click'; }"
                )
                if first:
                    _m04_log(f"[M04] 기법 B 결과: {ran}")
                clicked = True
            except Exception as e:
                if first:
                    _m04_log(f"[M04] 기법 B 실패: {e}")

        # 기법 C: 입력에 Enter
        if not clicked:
            try:
                await page.focus("#txt_srch_keyword")
                await page.keyboard.press("Enter")
                if first:
                    _m04_log("[M04] 기법 C (Enter) 시도")
            except Exception:
                pass

        # 4) tbody 변화 대기 (최대 6초)
        try:
            await page.wait_for_function(
                "prev => { const t = document.getElementById('tbody_winner_list'); "
                "if (!t) return false; const cur = (t.textContent || '').trim().slice(0, 200); "
                "return cur !== prev; }",
                arg=before, timeout=6000, polling=250,
            )
        except Exception:
            # 변화 없을 수도 (키워드별 낙찰 0건 가능) → 그래도 진행
            pass
        await page.wait_for_timeout(400)

        # 5) .topbar 요소 파싱 (VBA 방식)
        return await self._extract_bid_data(page, keyword, first)

    async def _extract_bid_data(self, page, keyword: str, debug: bool) -> dict:
        """#tbody_winner_list .topbar 요소를 VBA 방식으로 파싱.

        각 .topbar 텍스트는 "<rank> <price>" 형태 (줄바꿈/공백 구분).
        예: "1\\n5,100" 또는 "1 5,100".
        """
        try:
            parsed = await page.evaluate(
                "() => { const t = document.getElementById('tbody_winner_list'); "
                "if (!t) return {err: 'no-tbody'}; "
                "const bars = t.querySelectorAll('.topbar'); "
                "const items = []; "
                "bars.forEach(b => { "
                "  const text = (b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim(); "
                "  items.push(text); "
                "}); "
                "return { count: bars.length, items }; }"
            )
            if debug:
                _m04_log(f"[M04][DEBUG] '{keyword}' parsed: {parsed}")

            if parsed.get("err"):
                return {}

            bid_count = parsed.get("count", 0)
            items = parsed.get("items", [])

            # rank → price 맵 생성 (전체 순위 저장, 10위 초과도 포함)
            prices_by_rank: dict[int, int] = {}
            for item in items:
                # "rank price" 분리 (공백 구분)
                parts = item.split(" ")
                if len(parts) < 2:
                    continue
                rank_s = re.sub(r"\D", "", parts[0])
                price_s = re.sub(r"[^\d]", "", parts[1])
                if not rank_s or not price_s:
                    continue
                try:
                    r = int(rank_s)
                    p = int(price_s)
                except ValueError:
                    continue
                if r >= 1:
                    prices_by_rank[r] = p

            # bid_price_1 ~ bid_price_10 채우기
            #   bid_price_1  = rank 1 (낙찰종가, 최고가)
            #   bid_price_2~9 = rank 2~9 (중간 순위)
            #   bid_price_10 = 전체 낙찰 중 최저가 (rank = bid_count, 낙찰시가)
            # 낙찰수가 10 이하이면 bid_price_10 = rank(bid_count) 가 자연스럽게 됨.
            out: dict = {
                "keyword_jp": keyword,
                "lookup_date": date.today(),
                "index_key": f"{date.today()}_{keyword}",
                "bid_count": bid_count,
                "search_volume_weekly": 0,
                "search_volume_daily": 0,
            }
            out["bid_price_1"] = prices_by_rank.get(1, 0)
            for r in range(2, 10):
                out[f"bid_price_{r}"] = prices_by_rank.get(r, 0)
            # 최저가 = 가장 마지막 rank의 가격
            lowest_rank = max(prices_by_rank.keys()) if prices_by_rank else 0
            out["bid_price_10"] = prices_by_rank.get(lowest_rank, 0)
            return out
        except Exception as e:
            _m04_log(f"[M04] 파싱 실패 '{keyword}': {e}")
            return {}
