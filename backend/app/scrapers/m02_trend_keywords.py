import os
import re
import traceback
from datetime import date, datetime
from urllib.parse import unquote

from app.config import settings
from app.scrapers.base import BaseScraper

_DEBUG_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "m02_debug.log")


def _m02_log(msg: str) -> None:
    """print + append to debug file (사후 진단용)."""
    line = f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
    print(line)
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

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

# 큐텐 ADPlus 트렌드 페이지 dropdown에서 확인한 group_code 매핑
# (category=1은 종합 — group_code 필터 없이 전체 all_yn='Y' 행 중 p.rank.all 사용)
CATEGORY_GROUP_CODES: dict[int, str | None] = {
    1: None,   # 01.종합 — 전체
    2: "1",    # 02.여성패션
    3: "2",    # 03.뷰티&화장품
    4: "3",    # 04.남성&스포츠
    5: "4",    # 05.디지털
    6: "5",    # 06.홈&생활
    7: "6",    # 07.식품
    8: "10",   # 08.엔터테인먼트&e티켓
    9: "13",   # 09.베이비&키즈
    10: "14",  # 10.모바일
    11: "15",  # 11.펫 푸드&용품
    12: "16",  # 12.서플리먼트&다이어트
}


FIRST_KEYWORD_JS = (
    "() => { "
    "const td = document.querySelector(\"#tbody_popular_list tr[all_yn='Y'] td:nth-child(2)\"); "
    "if (!td) return ''; "
    "const c = td.cloneNode(true); "
    "c.querySelectorAll('table').forEach(t => t.remove()); "
    "return (c.textContent || '').trim(); }"
)

WAIT_CHANGE_JS = (
    "prev => { "
    "const td = document.querySelector(\"#tbody_popular_list tr[all_yn='Y'] td:nth-child(2)\"); "
    "if (!td) return false; "
    "const c = td.cloneNode(true); "
    "c.querySelectorAll('table').forEach(t => t.remove()); "
    "const cur = (c.textContent || '').trim(); "
    "return cur && cur !== prev; }"
)


class TrendKeywordScraper(BaseScraper):
    """M02: 인기/트렌드 키워드 추출"""

    async def _log_category_options(self, page, task_id) -> list[tuple[int, str, str]]:
        """select의 모든 option을 (index, value, text)로 수집/로그. 페이지당 1회."""
        opts = []
        options = await page.query_selector_all("#GROUP_CODE_PopAdplus option")
        for i, opt in enumerate(options, 1):
            val = (await opt.get_attribute("value")) or ""
            txt = (await opt.text_content() or "").strip()
            opts.append((i, val, txt))
        summary = ", ".join(f"{i}:{t}({v})" for i, v, t in opts)
        _m02_log(f"[M02][DEBUG] options: {summary}")
        self.tasks.update_progress(task_id, 0, f"[DEBUG] 카테고리 옵션: {summary}")

        # select 엘리먼트의 이벤트 바인딩 정보 조사 (원인 파악용)
        try:
            info = await page.evaluate(
                "() => { const s = document.getElementById('GROUP_CODE_PopAdplus'); "
                "if (!s) return {err: 'no select'}; "
                "const hasJq = !!(window.jQuery || window.$); "
                "let jqEvents = null; "
                "if (hasJq && window.jQuery && window.jQuery._data) { "
                "  try { jqEvents = Object.keys(window.jQuery._data(s, 'events') || {}); } "
                "  catch(e) { jqEvents = 'err:'+e.message; } "
                "} "
                "const popFns = Object.keys(window).filter(k => /popular|group|adplus|keyword/i.test(k)).slice(0, 30); "
                "return { onchange_attr: s.getAttribute('onchange'), onclick_attr: s.getAttribute('onclick'), hasJq, jqEvents, popFns }; }"
            )
            _m02_log(f"[M02][DEBUG] select info: {info}")
        except Exception as e:
            _m02_log(f"[M02][DEBUG] select info 조사 실패: {e}")

        # tbody 첫 3개 행의 속성 전수 조사 (group_code 확인)
        try:
            row_attrs = await page.evaluate(
                "() => { const rows = document.querySelectorAll('#tbody_popular_list tr'); "
                "const out = []; "
                "for (let i = 0; i < Math.min(rows.length, 5); i++) { "
                "  const r = rows[i]; "
                "  const attrs = {}; "
                "  for (const a of r.attributes) { attrs[a.name] = a.value; } "
                "  const td = r.querySelector('td:nth-child(2)'); "
                "  const c = td ? td.cloneNode(true) : null; "
                "  if (c) c.querySelectorAll('table').forEach(t => t.remove()); "
                "  const kw = c ? (c.textContent || '').trim().slice(0, 40) : ''; "
                "  out.push({ idx: i, attrs, kw, style: r.style.display || 'default' }); "
                "} "
                "const showFn = (window.Show || '').toString().slice(0, 3000); "
                "const groupCountsAllY = {}; "
                "document.querySelectorAll('#tbody_popular_list tr[all_yn=\"Y\"]').forEach(r => { "
                "  const g = r.getAttribute('group_code') || 'null'; "
                "  groupCountsAllY[g] = (groupCountsAllY[g] || 0) + 1; "
                "}); "
                "const groupCountsAll = {}; "
                "document.querySelectorAll('#tbody_popular_list tr[group_code]').forEach(r => { "
                "  const g = r.getAttribute('group_code') || 'null'; "
                "  groupCountsAll[g] = (groupCountsAll[g] || 0) + 1; "
                "}); "
                "const groupCountsMain = {}; "
                "document.querySelectorAll('#tbody_popular_list tr.pop_ad_plus_main_tr').forEach(r => { "
                "  const g = r.getAttribute('group_code') || 'null'; "
                "  groupCountsMain[g] = (groupCountsMain[g] || 0) + 1; "
                "}); "
                "return { rows: out, total: document.querySelectorAll('#tbody_popular_list tr').length, allYnTotal: document.querySelectorAll('#tbody_popular_list tr[all_yn=\"Y\"]').length, groupCountsAllY, groupCountsAll, groupCountsMain, Show_src: showFn }; }"
            )
            _m02_log(f"[M02][DEBUG] tbody rows: {row_attrs}")
        except Exception as e:
            _m02_log(f"[M02][DEBUG] tbody rows 조사 실패: {e}")

        # Category_PopAdplus 객체 속성/메서드 심층 조사 + OnChange 소스
        try:
            cat_info = await page.evaluate(
                "() => { const c = window.Category_PopAdplus; "
                "if (!c) return {err: 'no Category_PopAdplus'}; "
                "const keys = Object.keys(c); "
                "const props = {}; "
                "for (const k of keys) { "
                "  try { const v = c[k]; "
                "    props[k] = typeof v === 'function' ? 'fn' : (typeof v === 'object' ? (v===null?'null':'obj') : String(v).slice(0,80)); "
                "  } catch(e) { props[k] = 'err:'+e.message; } "
                "} "
                "const fn_oc = (window.GROUP_CODE_PopAdplus_OnChange || '').toString().slice(0, 1200); "
                "const fn_gdlc = (window.GDLC_CD_PopAdplus_OnChange || '').toString().slice(0, 800); "
                "const fn_regen = (c.ReGenGroup || '').toString().slice(0, 800); "
                "const hid_plus = (document.getElementById('hid_plus_type') || {}).value; "
                "const allHid = Array.from(document.querySelectorAll('input[type=hidden]')).map(h => ({id:h.id, name:h.name, val:(h.value||'').slice(0,40)})).slice(0,20); "
                "return { keys, props, OnChange_src: fn_oc, GDLC_OnChange_src: fn_gdlc, ReGenGroup_src: fn_regen, hid_plus, allHid }; }"
            )
            _m02_log(f"[M02][DEBUG] Category_PopAdplus: {cat_info}")
        except Exception as e:
            _m02_log(f"[M02][DEBUG] Category_PopAdplus 조사 실패: {e}")

        return opts

    async def _get_first_keyword(self, page) -> str:
        try:
            return (await page.evaluate(FIRST_KEYWORD_JS)) or ""
        except Exception:
            return ""

    async def _select_category(self, page, category: int, category_name: str, task_id) -> None:
        """VBA 방식(option 직접 클릭) → 폴백(select_option+change) 순서.
        첫 키워드 변화로 성공 판정, 실패 시 RuntimeError."""
        options = await page.query_selector_all("#GROUP_CODE_PopAdplus option")
        if not options or category > len(options):
            raise RuntimeError(f"[M02] option 부족: got {len(options)}, need {category}")
        option_el = options[category - 1]
        value = (await option_el.get_attribute("value")) or ""
        vis_text = (await option_el.text_content() or "").strip()
        before = await self._get_first_keyword(page)

        # 이미 해당 option이 선택된 상태면(페이지 기본값 = 종합 등) 재선택 불필요
        current_value = await page.evaluate(
            "() => { const s = document.getElementById('GROUP_CODE_PopAdplus'); return s ? s.value : ''; }"
        )
        if current_value == value and before:
            self.tasks.update_progress(
                task_id, 0,
                f"[DEBUG] cat={category}({category_name}) 이미 선택됨(value={value!r}) - 재선택 생략, 첫 키워드={before!r}"
            )
            _m02_log(f"[M02][DEBUG] cat={category} 이미 선택됨, skip (first={before!r})")
            return

        self.tasks.update_progress(
            task_id, 0,
            f"[DEBUG] cat={category}({category_name}) 선택: value={value!r} text={vis_text!r} before1위={before!r}"
        )
        _m02_log(f"[M02][DEBUG] cat={category} select value={value!r} text={vis_text!r} before={before!r}")

        async def _wait_change():
            await page.wait_for_function(WAIT_CHANGE_JS, arg=before, timeout=8000, polling=250)

        used = None
        errors = []

        # 기법 PRE-0: URL 파라미터로 재진입 시도 (가장 간단 — 먹히면 최고)
        try:
            base_url = f"{settings.QOO10_ADPLUS_URL}PopADPlusPopularKeyword.aspx"
            # 여러 param 이름 시도: 먼저 GROUP_CODE, 실패 시 group_code/groupCode
            test_url = f"{base_url}?plus_type=KW&GROUP_CODE={value}"
            await page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector("#tbody_popular_list tr", state="attached", timeout=10000)
            await page.wait_for_timeout(1500)  # AJAX 여유
            url_after = await self._get_first_keyword(page)
            _m02_log(f"[M02][DEBUG] 기법 URL: first={url_after!r}")
            if url_after and url_after != before:
                used = "URL-param"
                # fall through to after/check below
        except Exception as e_url:
            errors.append(f"URL={e_url}")
            _m02_log(f"[M02][DEBUG] 기법 URL 실패: {e_url}")

        # 기법 B: select_option + isCategoryTrigger ON 강제 후 onchange 속성 직접 실행
        if not used:
            try:
                if value:
                    await page.select_option("#GROUP_CODE_PopAdplus", value=value)
                else:
                    await page.select_option("#GROUP_CODE_PopAdplus", index=category - 1)
                await page.evaluate(
                    "() => { "
                    "try { if (window.Category_PopAdplus) window.Category_PopAdplus.isCategoryTrigger = 'ON'; } catch(e){} "
                    "const s = document.getElementById('GROUP_CODE_PopAdplus'); "
                    "if (s) { "
                    "  s.dispatchEvent(new Event('change', {bubbles:true})); "
                    "  const h = s.getAttribute('onchange'); "
                    "  if (h) { try { (new Function('event', h)).call(s); } catch(e){} } "
                    "} "
                    "try { window.GROUP_CODE_PopAdplus_OnChange && window.GROUP_CODE_PopAdplus_OnChange(); } catch(e){} "
                    "try { window.Category_PopAdplus && window.Category_PopAdplus.ReGenGroup && window.Category_PopAdplus.ReGenGroup(); } catch(e){} "
                    "}"
                )
                await _wait_change()
                used = "B-selectOption+handlers"
            except Exception as e_b:
                errors.append(f"B={e_b}")
                _m02_log(f"[M02][DEBUG] 기법 B 실패: {e_b}. 기법 C 시도")

        # 기법 C: jQuery change + onchange 속성 직접 실행 + window 로더 함수 탐색/호출
        if not used:
            try:
                fired = await page.evaluate(
                    "() => { const s = document.getElementById('GROUP_CODE_PopAdplus'); "
                    "if (!s) return {err:'no select'}; "
                    "const log = []; "
                    "try { if (window.jQuery) { window.jQuery(s).change(); log.push('jq.change'); } } catch(e) { log.push('jq-err:'+e.message); } "
                    "try { const h = s.getAttribute('onchange'); "
                    "  if (h) { (new Function('event', h)).call(s); log.push('attr-run'); } } catch(e) { log.push('attr-err:'+e.message); } "
                    "try { s.onchange && s.onchange(new Event('change')); log.push('onprop'); } catch(e) { log.push('onprop-err:'+e.message); } "
                    "for (const k of Object.keys(window)) { "
                    "  if (/^fn_.*(Popular|Group|AdPlus|Keyword)/i.test(k) || /^(get|load|search).*Popular/i.test(k)) { "
                    "    try { window[k](); log.push('call:'+k); break; } catch(e) { log.push('call-err:'+k+':'+e.message); } "
                    "  } "
                    "} "
                    "return { log }; }"
                )
                _m02_log(f"[M02][DEBUG] 기법 C fired: {fired}")
                await _wait_change()
                used = "C-jquery"
            except Exception as e_c:
                errors.append(f"C={e_c}")
                _m02_log(f"[M02][DEBUG] 기법 C 실패: {e_c}. 기법 D 시도")

        # 기법 D: select에 focus 후 키보드 입력 (실제 유저 제스처)
        if not used:
            try:
                await page.focus("#GROUP_CODE_PopAdplus")
                # value가 숫자 문자열인 경우 keyboard로 선택 가능 (select가 첫글자 매칭)
                # 더 확실한 방법: 몇 번 ArrowDown 후 Enter
                # options 인덱스만큼 ArrowDown (placeholder 포함 current index는 이미 placeholder=0)
                target_idx = category - 1  # placeholder 포함 0-index
                # 현재 selected index 조회
                cur_idx = await page.evaluate(
                    "() => { const s = document.getElementById('GROUP_CODE_PopAdplus'); return s ? s.selectedIndex : -1; }"
                )
                delta = target_idx - (cur_idx if cur_idx >= 0 else 0)
                key = "ArrowDown" if delta > 0 else "ArrowUp"
                for _ in range(abs(delta)):
                    await page.keyboard.press(key)
                await page.keyboard.press("Enter")
                await _wait_change()
                used = "D-keyboard"
            except Exception as e_d:
                errors.append(f"D={e_d}")

        if not used:
            raise RuntimeError(
                f"[M02] category {category} ({category_name}) selection failed: "
                f"{'; '.join(errors)}; first_kw stuck at {before!r}"
            )

        after = await self._get_first_keyword(page)
        self.tasks.update_progress(
            task_id, 0,
            f"[DEBUG] cat={category}({category_name}) {used} 성공: before={before!r} → after={after!r}"
        )
        _m02_log(f"[M02][DEBUG] cat={category} {used} before={before!r} after={after!r}")
        if not after or after == before:
            raise RuntimeError(
                f"[M02] category {category} ({category_name}) 변화 없음: {before!r} == {after!r}"
            )

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

            # 카테고리 분리: 큐텐 페이지는 전체 데이터(3500+행)를 한 번 로드하고
            # `group_code` 속성 + `p.rank.group` 클래스로 클라이언트 사이드 필터링을 함.
            # → dropdown 조작 불필요. tr[group_code=X] 행만 추려 rank.group 값을 순위로 사용.
            await self._log_category_options(page, task_id)
            category_name = CATEGORIES.get(category, "01.종합")
            group_code = CATEGORY_GROUP_CODES.get(category)
            per_cat_limit = 100 if category == 1 else 30
            self.tasks.update_progress(
                task_id, 0,
                f"'{category_name}' 키워드 추출 (group_code={group_code or '전체'}, limit={per_cat_limit})"
            )
            all_keywords = []

            if "popular" in types:
                keywords = await self._extract_keywords(
                    page, "tbody_popular_list", category_name, "1.주요", task_id,
                    group_code=group_code, limit=per_cat_limit,
                )
                print(f"[M02] 주요 키워드: {len(keywords)}개")
                all_keywords.extend(keywords)

            if "daily" in types:
                keywords = await self._extract_keywords(
                    page, "tbody_daily_list", category_name, "2.일간", task_id,
                    group_code=group_code, limit=10,
                )
                print(f"[M02] 일간 키워드: {len(keywords)}개")
                all_keywords.extend(keywords)

            if "weekly" in types:
                keywords = await self._extract_keywords(
                    page, "tbody_weekly_list", category_name, "3.주간", task_id,
                    group_code=group_code, limit=10,
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
        self, page, table_id: str, category: str, classification: str, task_id: str,
        group_code: str | None = None, limit: int = 100,
    ) -> list[dict]:
        """
        HTML 구조 (실제 확인됨):
        <tr id="tr_0" all_yn="Y" group_code="2" gdlc_cd="..." gdmc_cd="...">
          <td><p class="rank all">1</p><p class="rank group">3</p></td>
          <td>カーテン (4)<table ...>...</table></td>
          ...
        </tr>

        group_code가 지정되면 해당 카테고리 행만 추출하고 p.rank.group 값을 순위로 사용.
        None이면(=종합) 전체 행에서 p.rank.all 값을 순위로 사용.
        """
        keywords = []

        tbody = await page.query_selector(f"#{table_id}")
        if not tbody:
            print(f"[M02] #{table_id} 못 찾음")
            return keywords

        if group_code is None:
            # 종합: all_yn='Y' 전역 톱 100
            selector = "tr[all_yn='Y']"
            rank_selector = "p.rank.all"
        else:
            # 카테고리별: tr[group_code=X] (all_yn 조건 없음 — 서버가 카테고리별 30행 렌더)
            selector = f"tr.pop_ad_plus_main_tr[group_code='{group_code}']"
            rank_selector = "p.rank.group"

        rows = await tbody.query_selector_all(selector)
        if not rows and group_code is None:
            rows = await tbody.query_selector_all("tr[id^='tr_']")

        print(f"[M02] #{table_id} (group={group_code or '전체'}): {len(rows)}개 행")
        _m02_log(f"[M02][DEBUG] #{table_id} group={group_code or 'ALL'} matched={len(rows)}")

        seen_ranks: set[int] = set()

        for row in rows:
            if len(keywords) >= limit:
                break
            try:
                tds = await row.query_selector_all(":scope > td")
                if len(tds) < 4:
                    continue

                # 1. 순위: group 지정 시 p.rank.group, 없으면 p.rank.all, fallback p.rank
                rank_el = (
                    await tds[0].query_selector(rank_selector)
                    or await tds[0].query_selector("p.rank.all")
                    or await tds[0].query_selector("p.rank")
                )
                if not rank_el:
                    rank_text = await tds[0].text_content()
                else:
                    rank_text = await rank_el.text_content()
                rank_clean = re.sub(r"\D", "", rank_text.strip())
                if not rank_clean:
                    continue
                rank = int(rank_clean)
                # 중복 순위 방어 (rank 0이나 중복 rank 행은 표시용 노이즈)
                if rank == 0 or rank in seen_ranks:
                    continue
                seen_ranks.add(rank)

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

                # 유효성: 빈값, 괄호숫자만은 비정상. 순수 숫자는 JAN/바코드형 유효 키워드.
                if (not keyword
                        or re.fullmatch(r"\(\s*\d+\s*\)", keyword)):
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
