"""한국 SKU URL → 상품 정보 자동 추출 (ZZZ-1).

사장님이 시트 needs_search row 에 한국 셀러 URL 직접 입력 시 자동으로:
  - product_name
  - cover_image_url
  - price_krw
  - options (단품 외 변형)
  - shipping (배송 종류/금액)

Naver smartstore / brand.naver.com 의 SSR HTML 에 __NEXT_DATA__ JSON 내장됨.
Playwright captcha 우회 — httpx + stealth headers + JSON 파싱.

지원 URL:
  - smartstore.naver.com/{mall}/products/{productId}
  - brand.naver.com/{mall}/products/{productId}
  - shopping.naver.com (search/redirect)
  - 쿠팡 (별도 처리)
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# Stealth headers — 실제 Chrome 브라우저 UA + 한국어 + Referer
_STEALTH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# URL 파싱 — Naver smartstore / brand 통일
_NAVER_PRODUCT_URL_RE = re.compile(
    r"https?://(?:smartstore|brand)\.naver\.com/([^/]+)/products/(\d+)"
)


def parse_naver_url(url: str) -> dict | None:
    """URL → {mallName, productId, host}. 매칭 안되면 None."""
    if not url:
        return None
    m = _NAVER_PRODUCT_URL_RE.search(url)
    if not m:
        return None
    mall = m.group(1)
    pid = m.group(2)
    host = "brand.naver.com" if "brand.naver.com" in url else "smartstore.naver.com"
    return {"mallName": mall, "productId": pid, "host": host}


def _extract_next_data(html: str) -> dict | None:
    """Naver smartstore SSR HTML 에 내장된 __NEXT_DATA__ JSON 추출."""
    # Next.js __NEXT_DATA__ pattern
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL,
    )
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    # Nuxt __NUXT_DATA__ pattern (다른 Naver 페이지 fallback)
    m = re.search(
        r'<script[^>]+id="__NUXT_DATA__"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


def _flatten_search(obj, key_path: list[str], depth: int = 0, max_depth: int = 8) -> any:
    """JSON tree 에서 첫 번째 매칭 key path 값 반환."""
    if depth > max_depth or not key_path:
        return None
    if isinstance(obj, dict):
        if key_path[0] in obj:
            if len(key_path) == 1:
                return obj[key_path[0]]
            return _flatten_search(obj[key_path[0]], key_path[1:], depth + 1, max_depth)
        for v in obj.values():
            r = _flatten_search(v, key_path, depth + 1, max_depth)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _flatten_search(item, key_path, depth + 1, max_depth)
            if r is not None:
                return r
    return None


def _parse_naver_product(data: dict) -> dict:
    """__NEXT_DATA__ JSON → 표준 product info 구조."""
    out = {
        "product_name": "",
        "price_krw": 0,
        "cover_image_url": "",
        "options": [],
        "shipping_text": "",
        "extra_image_urls": [],
        "weight_g": None,
    }
    if not data:
        return out

    # 일반 path: props.pageProps.product (Next.js SSR 표준)
    product = (
        _flatten_search(data, ["props", "pageProps", "product"])
        or _flatten_search(data, ["pageProps", "product"])
        or _flatten_search(data, ["product"])
    )
    if not product or not isinstance(product, dict):
        return out

    out["product_name"] = product.get("name") or product.get("productName") or ""
    out["price_krw"] = int(
        product.get("salePrice")
        or product.get("price")
        or product.get("dispSalePrice")
        or 0
    )

    # cover image
    images = product.get("productImages") or product.get("images") or []
    if images and isinstance(images, list):
        first = images[0]
        if isinstance(first, dict):
            out["cover_image_url"] = first.get("url") or first.get("imageUrl") or ""
        elif isinstance(first, str):
            out["cover_image_url"] = first
    if not out["cover_image_url"]:
        out["cover_image_url"] = product.get("representImageUrl") or ""

    # options (옵션 조합)
    opts = product.get("optionCombinations") or product.get("options") or []
    if isinstance(opts, list):
        for o in opts[:30]:
            if isinstance(o, dict):
                name = (
                    o.get("optionName1") or o.get("name") or o.get("displayName") or ""
                )
                if o.get("optionName2"):
                    name = f"{name} / {o.get('optionName2')}"
                price = int(o.get("price") or o.get("optionPrice") or out["price_krw"] or 0)
                stock = bool(o.get("stockQuantity", 1) > 0) if o.get("stockQuantity") is not None else True
                if name:
                    out["options"].append({
                        "name": name, "price_krw": price, "in_stock": stock,
                    })

    # shipping
    delivery = product.get("productDeliveryInfo") or product.get("delivery") or {}
    if isinstance(delivery, dict):
        out["shipping_text"] = (
            delivery.get("baseFee")
            and f"배송비 {delivery.get('baseFee'):,}원"
            or delivery.get("deliveryFee")
            and f"배송비 {delivery.get('deliveryFee'):,}원"
            or ""
        )

    # extra detail images
    detail_imgs = product.get("detailContents") or []
    if isinstance(detail_imgs, list):
        for img_url in detail_imgs[:10]:
            if isinstance(img_url, str) and img_url.startswith("http"):
                out["extra_image_urls"].append(img_url)

    return out


async def fetch_naver_url(url: str, timeout: float = 15.0) -> dict:
    """URL → product info via httpx (stealth) + JSON parsing.

    실패 시 {error, ...} 반환.
    """
    parsed = parse_naver_url(url)
    if not parsed:
        return {"error": "Naver smartstore/brand URL 아님"}

    headers = dict(_STEALTH_HEADERS)
    headers["Referer"] = f"https://search.shopping.naver.com/search/all?query={parsed['mallName']}"

    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers,
        ) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return {"error": f"HTTP {r.status_code}"}
            html = r.text
    except Exception as e:
        return {"error": f"fetch fail: {type(e).__name__}: {e}"}

    if "captcha" in html.lower() or "시스템점검" in html or "비정상" in html:
        return {"error": "captcha or block detected"}

    data = _extract_next_data(html)
    if not data:
        return {"error": "__NEXT_DATA__ JSON 추출 실패"}

    info = _parse_naver_product(data)
    info["url"] = url
    info["mallName"] = parsed["mallName"]
    info["productId"] = parsed["productId"]
    return info


__all__ = ["parse_naver_url", "fetch_naver_url"]
