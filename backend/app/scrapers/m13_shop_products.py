"""M13: 큐텐 샵 벤치마크.

지정한 샵 URL(예: https://www.qoo10.jp/shop/tsurutsuru)에서 판매 중인 상품을
판매량/순위순으로 최대한 많이 수집한다. 벤치마킹 대상 셀러 분석용.
"""
import re
from datetime import date
from urllib.parse import urlparse

from app.scrapers.base import BaseScraper


def _normalize_shop_url(shop_url_or_id: str) -> tuple[str, str]:
    """샵 URL 또는 shop_id를 받아 (full_url, shop_id) 반환."""
    s = shop_url_or_id.strip()
    if s.startswith("http"):
        path = urlparse(s).path.rstrip("/")
        shop_id = path.rsplit("/", 1)[-1] if path else s
        return s.rstrip("/"), shop_id
    # 순수 id
    return f"https://www.qoo10.jp/shop/{s}", s


class Qoo10ShopScraper(BaseScraper):
    """샵 페이지의 상위 순위 상품 수집.

    정렬 옵션: 큐텐 샵이 제공하는 5가지 정렬을 JS click으로 적용.
    sort_type:
      - 'ranking' (기본, ランキング順)
      - 'review'  (リヴューが多い順, 리뷰 많은순 — 실적 프록시)
      - 'new'     (新着順, 신착순)
      - 'price_high' (価格が高い順)
      - 'price_low'  (価格が安い順)
    """

    SORT_LABELS = {
        "ranking": "ランキング順",
        "review": "レビューが多い順",
        "new": "新着順",
        "price_high": "価格が高い順",
        "price_low": "価格が安い順",
    }

    async def run(self, shop_url: str, limit: int = 50, sort_type: str = "ranking", **params) -> dict:
        page = await self.browser.get_page()
        full_url, shop_id = _normalize_shop_url(shop_url)
        sort_label = self.SORT_LABELS.get(sort_type, self.SORT_LABELS["ranking"])

        task_id = self.tasks.create_task(f"샵 상품 수집 ({shop_id})", 1)
        self.tasks.start_task(task_id)

        try:
            self.tasks.update_progress(task_id, 0, f"{full_url} 접속")
            await page.goto(full_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)

            # 정렬 클릭 (기본 ランキング順은 클릭 불필요)
            # 큐텐 샵은 드롭다운 형태: 먼저 선택된 버튼 클릭해서 열어야 옵션들에 접근 가능
            debug = {"sort_type": sort_type, "sort_label": sort_label, "sort_applied": False}
            if sort_type != "ranking":
                try:
                    # 1) 드롭다운 버튼 클릭해서 옵션 목록 펼치기
                    try:
                        await page.click('button.val[title*="並べ替え"], button.val', timeout=3000)
                        await page.wait_for_timeout(400)
                    except Exception:
                        pass

                    # 2) 원하는 정렬 옵션 클릭 (force로 오버레이 무시)
                    sort_selectors = [
                        f'a:has-text("{sort_label}")',
                        f'[val]:has-text("{sort_label}")',
                    ]
                    clicked = False
                    for sel in sort_selectors:
                        try:
                            await page.click(sel, force=True, timeout=3000)
                            clicked = True
                            break
                        except Exception:
                            continue

                    if clicked:
                        await page.wait_for_timeout(2500)
                        debug["sort_applied"] = True
                    else:
                        # 폴백: JS로 직접 onclick 호출
                        val_map = {
                            "review": "MOST_REVIEWED",
                            "new": "NEWLY_LISTED",
                            "price_high": "PRICE_DESC",
                            "price_low": "PRICE_ASC",
                        }
                        val = val_map.get(sort_type)
                        if val:
                            try:
                                await page.evaluate(f'''
                                    (() => {{
                                        const el = document.querySelector('a[val="{val}"]');
                                        if (el && window.setSearchValues) {{
                                            window.setSearchValues('sortType', el);
                                            return true;
                                        }}
                                        return false;
                                    }})()
                                ''')
                                await page.wait_for_timeout(2500)
                                debug["sort_applied"] = True
                                debug["sort_method"] = "js_fallback"
                            except Exception as e:
                                debug["sort_js_error"] = str(e)[:200]
                except Exception as e:
                    debug["sort_error"] = f"{type(e).__name__}: {str(e)[:300]}"

            # 스크롤 (lazy load 대비)
            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)

            debug["final_url"] = page.url
            for sel in [".item", ".s_item", ".list_item"]:
                els = await page.query_selector_all(sel)
                if els:
                    debug["item_counts"] = debug.get("item_counts", {})
                    debug["item_counts"][sel] = len(els)

            products = await self._extract_products(page, shop_id, limit)

            self.tasks.complete_task(task_id, f"{len(products)}개 상품 수집")
            return {
                "task_id": task_id, "shop_id": shop_id, "shop_url": full_url,
                "sort_type": sort_type, "sort_label": sort_label,
                "products": products, "debug": debug,
            }

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e), "products": []}

    async def _extract_products(self, page, shop_id: str, limit: int) -> list[dict]:
        """샵 페이지 상품 목록에서 상품 정보 + 순위 추출.

        큐텐 샵 DOM 구조 (2026-04 확인):
          .item
            a.thmb[href]   → 상품 URL + <img src> → 썸네일
            a.txt_brand    → 브랜드명
            a.tt[title]    → 상품명 (title + inner text 동일)
            .prc strong    → 가격 "1,950円"
            .review_total_count → "(212)"
            .etc .ship     → 배송비 ("送料無料")
        """
        products: list[dict] = []

        # .item이 큐텐 샵의 실제 컨테이너. 다른 셀렉터는 폴백.
        selectors = [".item", ".s_item_group .s_item", ".s_item", "[class*='product-item']", ".list_item"]
        items = []
        for sel in selectors:
            items = await page.query_selector_all(sel)
            if items and len(items) >= 3:  # 메뉴 등 노이즈 배제
                break

        if not items:
            return products

        for rank, item in enumerate(items[:limit], start=1):
            try:
                product: dict = {}

                # 상품명: a.tt[title] 우선
                name_el = await item.query_selector("a.tt")
                if name_el:
                    title = await name_el.get_attribute("title")
                    text = (await name_el.inner_text()).strip()
                    product["product_name"] = (title or text or "").strip()
                if not product.get("product_name"):
                    alt_name = await item.query_selector("a[title]")
                    if alt_name:
                        product["product_name"] = (await alt_name.get_attribute("title") or "").strip()

                # 가격: .prc strong
                price_el = await item.query_selector(".prc strong")
                if not price_el:
                    price_el = await item.query_selector(".prc, .price, [class*='price']")
                if price_el:
                    price_text = await price_el.inner_text()
                    nums = re.sub(r"[^\d]", "", price_text)
                    product["price_jpy"] = int(nums) if nums else 0
                else:
                    product["price_jpy"] = 0

                # 배송비: .etc .ship 또는 .ship
                ship_el = await item.query_selector(".etc .ship, .ship, [class*='shipping']")
                product["shipping_fee"] = (await ship_el.inner_text()).strip() if ship_el else ""

                # 출하지 (큐텐 샵은 대부분 출하지 명시 안 함)
                origin_el = await item.query_selector(".national, [class*='origin'], [class*='country']")
                product["origin"] = (await origin_el.inner_text()).strip() if origin_el else ""

                # 이미지: a.thmb img
                img_el = await item.query_selector("a.thmb img, img")
                if img_el:
                    src = await img_el.get_attribute("src") or await img_el.get_attribute("data-src") or ""
                    product["cover_image_url"] = src

                # 링크: a.thmb[href] 또는 a.tt[href]
                link_el = await item.query_selector("a.thmb[href], a.tt[href]")
                if not link_el:
                    link_el = await item.query_selector("a[href]")
                if link_el:
                    href = await link_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = f"https://www.qoo10.jp{href}"
                    product["product_url"] = href

                # 브랜드
                brand_el = await item.query_selector("a.txt_brand")
                if brand_el:
                    product["brand"] = (await brand_el.inner_text()).strip()

                # 리뷰 수: .review_total_count "(212)" → 212
                rev_count = 0
                for rev_sel in [
                    ".review_total_count",
                    "span.review_total_count",
                    "[class*='review_total_count']",
                ]:
                    rev_el = await item.query_selector(rev_sel)
                    if rev_el:
                        rev_text = await rev_el.inner_text()
                        rev_nums = re.sub(r"[^\d]", "", rev_text)
                        if rev_nums:
                            rev_count = int(rev_nums)
                            break
                product["review_count"] = rev_count

                product["search_keyword"] = f"shop:{shop_id}"
                product["shop_id"] = shop_id
                product["shop_rank"] = rank
                product["lookup_date"] = date.today()

                # 상품명 없으면 스킵 (메뉴 요소 등)
                if product.get("product_name"):
                    products.append(product)

            except Exception:
                continue

        return products
