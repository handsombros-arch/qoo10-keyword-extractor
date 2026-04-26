"""M07: 쿠팡 상품 검색 (Scrapling StealthyFetcher 기반).

쿠팡은 Cloudflare-style 봇 탐지가 강해서 일반 Playwright Chromium 으로는
Access Denied(403) 가 떨어진다. Scrapling 의 StealthyFetcher(camoufox 기반
stealth Firefox)로 우회한다.

선행 설치 (한 번만):
    pip install --user "scrapling[fetchers]"
    playwright install
    python -m scrapling install     # camoufox 다운로드
"""
from __future__ import annotations

import asyncio
import re
from datetime import date

from app.scrapers.base import BaseScraper


_PRICE_RE = re.compile(r"\d{1,3}(?:,\d{3})+")


class CoupangScraper(BaseScraper):
    """M07: 쿠팡 상품 검색."""

    async def run(self, keyword: str, **params) -> dict:
        task_id = self.tasks.create_task("쿠팡 상품 검색", 1)
        self.tasks.start_task(task_id)

        try:
            try:
                from scrapling.fetchers import StealthyFetcher  # noqa: F401
            except ImportError:
                self.tasks.fail_task(task_id, "scrapling 미설치")
                return {
                    "task_id": task_id,
                    "products": [],
                    "error": "scrapling 미설치 — pip install \"scrapling[fetchers]\" + python -m scrapling install",
                }

            self.tasks.update_progress(task_id, 0, f"'{keyword}' 쿠팡 검색 중...")
            url = f"https://www.coupang.com/np/search?q={keyword}&channel=user"

            page = await asyncio.to_thread(_stealth_fetch, url)
            if page is None:
                self.tasks.fail_task(task_id, "쿠팡 fetch 실패")
                return {"task_id": task_id, "products": []}

            products = _extract_products(page, keyword)
            self.tasks.complete_task(task_id, f"{len(products)}개 상품 수집")
            return {"task_id": task_id, "products": products}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e), "products": []}


def _stealth_fetch(url: str):
    """동기 — asyncio.to_thread 로 호출됨.

    Scrapling 버전마다 지원 옵션이 다를 수 있어 단계적으로 제거하며 재시도.
    """
    from scrapling.fetchers import StealthyFetcher

    kwargs = {
        "headless": True,            # 백엔드가 이미 헤드풀 큐텐 창을 쓰므로 쿠팡은 헤드리스
        "network_idle": True,
        "google_search": True,
        "block_images": True,        # 이미지 안 받으면 빠름 (HTML alt에 상품명 있음)
        "humanize": True,
        "solve_cloudflare": True,
        "wait": 3000,
    }
    optional = ["solve_cloudflare", "humanize", "google_search"]
    last_err: Exception | None = None
    for attempt in range(len(optional) + 1):
        try:
            return StealthyFetcher.fetch(url, **kwargs)
        except TypeError as e:
            last_err = e
            if attempt < len(optional):
                kwargs.pop(optional[attempt], None)
            else:
                raise
        except Exception as e:
            # 네트워크/타임아웃 등은 그대로 전파
            raise
    if last_err:
        raise last_err
    return None


def _text_or_empty(node) -> str:
    """Scrapling Adaptor 의 텍스트 추출 — 버전 호환."""
    if node is None:
        return ""
    for attr in ("text", "text_content", "html_content"):
        v = getattr(node, attr, None)
        if isinstance(v, str):
            return v.strip()
        if callable(v):
            try:
                r = v()
                if isinstance(r, str):
                    return r.strip()
            except Exception:
                pass
    try:
        return str(node).strip()
    except Exception:
        return ""


def _attr_or_empty(node, key: str) -> str:
    if node is None:
        return ""
    # Scrapling: node.attrib['key'] 또는 node.attrib.get
    try:
        attrib = getattr(node, "attrib", None)
        if attrib is not None:
            try:
                v = attrib.get(key) if hasattr(attrib, "get") else attrib[key]
            except Exception:
                v = None
            if v:
                return str(v).strip()
    except Exception:
        pass
    # 폴백: dict-like
    try:
        v = node[key]
        if v:
            return str(v).strip()
    except Exception:
        pass
    return ""


def _extract_products(page, keyword: str) -> list[dict]:
    """쿠팡 검색 결과에서 상품 카드 추출.

    구조 (2026):
        <li class="ProductUnit_productUnit__..." data-id="...">
            <a href="/vp/products/..."> ... </a>
            <img alt="상품명">
            <div class="ProductUnit_productNameV2__...">상품명 텍스트</div>
            <div class="PriceArea_priceArea__..."> ... 19,000원 ... </div>
        </li>
    """
    products: list[dict] = []

    try:
        items = page.css("li[class*='ProductUnit_productUnit']")
    except Exception:
        items = []

    if not items:
        return products

    for item in list(items)[:30]:
        try:
            product = {
                "source": "coupang",
                "search_keyword": keyword,
                "lookup_date": date.today(),
                "shipping_fee": "",
                "origin": "",
            }

            # 상품명
            name_el = item.css_first("[class*='ProductUnit_productNameV2']")
            name = _text_or_empty(name_el)
            if not name:
                # 폴백: img alt
                img_el = item.css_first("img[alt]")
                name = _attr_or_empty(img_el, "alt")
            product["product_name"] = name

            # 가격 — PriceArea 안의 가격 텍스트 중 첫 매치(=주 가격)
            price_block = item.css_first("[class*='PriceArea_priceArea']")
            block_text = _text_or_empty(price_block)
            price_krw = 0
            if block_text:
                m = _PRICE_RE.search(block_text)
                if m:
                    price_krw = int(m.group(0).replace(",", ""))
            product["price_krw"] = price_krw

            # 이미지
            img_el = item.css_first("img")
            product["cover_image_url"] = _attr_or_empty(img_el, "src")

            # 링크
            link_el = item.css_first("a[href*='/vp/products/']")
            href = _attr_or_empty(link_el, "href")
            if href and not href.startswith("http"):
                href = f"https://www.coupang.com{href}"
            product["product_url"] = href

            if product.get("product_name"):
                products.append(product)

        except Exception:
            continue

    return products
