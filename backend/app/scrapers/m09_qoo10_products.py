import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from app.config import settings
from app.scrapers.base import BaseScraper


_DEBUG_DIR = Path(settings.DATA_DIR) / "m09_debug"
_DEBUG_DIR.mkdir(parents=True, exist_ok=True)


class Qoo10ProductScraper(BaseScraper):
    """M09: Qoo10 상품 검색"""

    async def run(self, keyword: str, keyword_jp: str = None, **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("Qoo10 상품 검색", 1)
        self.tasks.start_task(task_id)

        try:
            search_kw = keyword_jp or keyword
            self.tasks.update_progress(task_id, 0, f"'{search_kw}' 검색 중...")

            # 쿼리스트링 형식 — path 형식은 옛 페이지로 라우팅됨
            search_url = f"https://www.qoo10.jp/s/?keyword={quote(search_kw)}"
            await page.goto(search_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            # 스크롤하여 더 많은 상품 로드
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)

            products = await self._extract_products(page, keyword)

            # 0건이면 디버그 정보 저장 — page url/title + HTML 일부
            if not products:
                try:
                    debug_url = page.url
                    debug_title = await page.title()
                    html = await page.content()
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_kw = re.sub(r"[^\w]", "_", keyword)[:30]
                    debug_path = _DEBUG_DIR / f"{ts}_{safe_kw}.html"
                    debug_path.write_text(html, encoding="utf-8")
                    msg = (
                        f"0건 (디버그 저장: {debug_path.name}) "
                        f"url={debug_url[:80]} title={debug_title[:60]}"
                    )
                except Exception as de:
                    msg = f"0개 상품 (디버그 저장 실패: {de})"
                self.tasks.complete_task(task_id, msg)
            else:
                self.tasks.complete_task(task_id, f"{len(products)}개 상품 수집 완료")
            return {"task_id": task_id, "products": products}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    async def _extract_products(self, page, keyword: str) -> list[dict]:
        """상품 정보 추출.

        2026 큐텐 검색 페이지 구조:
            <tbody id="search_result_item_list">
                <tr goodscode="..." id="g_...">
                    <td class="td_thmb"> <a><img gd_src="..."></a> </td>
                    <td class="td_item"> <div class="sbj"><a class="txt_brand">브랜드</a><a title="상품명">상품명</a></div> </td>
                    <td class="td_prc"> <div class="prc"><strong>2,211円</strong></div> </td>
                    <td class="td_ship"> <div class="ship_area"><div class="shp_ntn">KR</div></div> </td>
                </tr>
        """
        products = []

        # 새 구조 (2026~) — 테이블 행
        items = await page.query_selector_all(
            "tbody#search_result_item_list > tr[goodscode]"
        )

        # 폴백: 옛 카드 구조
        if not items:
            items = await page.query_selector_all(
                ".s_item_group .s_item, [class*='product-item']"
            )

        for item in items[:50]:
            try:
                product: dict = {
                    "search_keyword": keyword,
                    "lookup_date": date.today(),
                }

                # 상품명 — sbj 안의 a 중 .txt_brand 가 아닌 것 (즉 상품 링크)
                name_el = await item.query_selector(
                    "td.td_item .sbj a[title]:not(.txt_brand)"
                )
                if not name_el:
                    # 폴백: sbj 의 마지막 a, 또는 td_item 안 어디든 title 있는 a
                    name_el = await item.query_selector("td.td_item a[title]")
                if not name_el:
                    name_el = await item.query_selector("a[title], .sbj a, .tit")
                if name_el:
                    name = (await name_el.inner_text()).strip()
                    if not name:
                        # inner_text 가 비면 title 속성 사용
                        name = (await name_el.get_attribute("title") or "").strip()
                    product["product_name"] = name

                # 가격 — td.td_prc .prc strong
                price_el = await item.query_selector("td.td_prc .prc strong")
                if not price_el:
                    price_el = await item.query_selector(".prc strong, .price")
                if price_el:
                    price_text = await price_el.inner_text()
                    nums = re.sub(r"[^\d]", "", price_text)
                    product["price_jpy"] = int(nums) if nums else 0

                # 배송비 — td.td_ship .ship 텍스트
                ship_el = await item.query_selector("td.td_ship .ship")
                if not ship_el:
                    ship_el = await item.query_selector(
                        ".ship, [class*='shipping'], [class*='delivery']"
                    )
                if ship_el:
                    product["shipping_fee"] = (await ship_el.inner_text()).strip()
                else:
                    product["shipping_fee"] = ""

                # 출하지 — td.td_ship .shp_ntn (텍스트 'KR' 또는 title 속성 '韓国')
                origin_el = await item.query_selector("td.td_ship .shp_ntn")
                if not origin_el:
                    origin_el = await item.query_selector(
                        ".shp_ntn, .national, [class*='origin'], [class*='country']"
                    )
                if origin_el:
                    origin_text = (await origin_el.inner_text()).strip()
                    if not origin_text:
                        origin_text = (await origin_el.get_attribute("title") or "").strip()
                    product["origin"] = origin_text
                else:
                    product["origin"] = ""

                # 이미지 — td.td_thmb img, lazy-load 패턴 (gd_src 우선)
                img_el = await item.query_selector("td.td_thmb img")
                if not img_el:
                    img_el = await item.query_selector("img")
                if img_el:
                    gd_src = await img_el.get_attribute("gd_src") or ""
                    data_src = await img_el.get_attribute("data-src") or ""
                    src = await img_el.get_attribute("src") or ""
                    chosen = ""
                    for c in (gd_src, data_src, src):
                        if c and "loading" not in c.lower():
                            chosen = c
                            break
                    product["cover_image_url"] = chosen or src

                # 링크 — td.td_thmb a, 또는 sbj 안 상품 링크
                link_el = await item.query_selector("td.td_thmb a[href]")
                if not link_el:
                    link_el = await item.query_selector(
                        "td.td_item .sbj a[href]:not(.txt_brand)"
                    )
                if not link_el:
                    link_el = await item.query_selector("a[href]")
                if link_el:
                    href = await link_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = f"https://www.qoo10.jp{href}"
                    product["product_url"] = href

                if product.get("product_name"):
                    products.append(product)

            except Exception:
                continue

        return products
