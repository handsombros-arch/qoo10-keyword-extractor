"""Naver smartstore/brand URL → product info via Playwright (kc-cert-checker 패턴).

핵심:
  - Playwright 가 Chrome 직접 launch (포트 9222 attach 사용 X)
  - --disable-blink-features=AutomationControlled flag 로 navigator.webdriver 우회
  - 사장님 메인 Chrome 재시작 X
  - cookies persist (data/naver_cookies.json) — 첫 captcha 1회만 사장님 풀어주면 영구

env:
  NAVER_COOKIES_PATH (default backend/data/naver_cookies.json)
  CHROME_EXECUTABLE  (default C:/Program Files/Google/Chrome/Application/chrome.exe)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_NAVER_PRODUCT_URL_RE = re.compile(
    r"https?://(?:smartstore|brand)\.naver\.com/([^/]+)/products/(\d+)"
)


def _cookies_path() -> Path:
    p = os.getenv("NAVER_COOKIES_PATH")
    if p:
        return Path(p)
    return Path(__file__).resolve().parent.parent.parent / "data" / "naver_cookies.json"


def _chrome_exe() -> str | None:
    p = os.getenv("CHROME_EXECUTABLE")
    if p and Path(p).exists():
        return p
    for c in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ):
        if Path(c).exists():
            return c
    return None


def parse_naver_url(url: str) -> dict | None:
    m = _NAVER_PRODUCT_URL_RE.search(url)
    if not m:
        return None
    return {
        "mallName": m.group(1),
        "productId": m.group(2),
        "host": "brand.naver.com" if "brand.naver.com" in url else "smartstore.naver.com",
    }


def _extract_json_ld(html: str) -> dict | None:
    """Naver smartstore SSR HTML 의 JSON-LD Product schema 추출."""
    matches = re.findall(
        r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    for raw in matches:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        # @type Product 우선
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
        # 또는 list 형태
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    return item
    return None


def _extract_next_data(html: str) -> dict | None:
    """legacy __NEXT_DATA__ — fallback (JSON-LD 우선)."""
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _flatten_search(obj, key_path: list[str], depth: int = 0, max_depth: int = 8):
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


def _parse_json_ld(data: dict) -> dict:
    """JSON-LD Product schema → 표준 product info."""
    out = {
        "product_name": "",
        "price_krw": 0,
        "cover_image_url": "",
        "options": [],
        "shipping_text": "",
        "extra_image_urls": [],
        "weight_g": None,
        "category_path": "",
        "description": "",
    }
    if not data:
        return out
    out["product_name"] = data.get("name") or ""
    out["description"] = (data.get("description") or "")[:500]
    out["category_path"] = data.get("category") or ""
    img = data.get("image")
    if isinstance(img, str):
        out["cover_image_url"] = img
        out["extra_image_urls"].append(img)
    elif isinstance(img, list) and img:
        out["cover_image_url"] = img[0]
        out["extra_image_urls"] = [u for u in img if isinstance(u, str)]
    offers = data.get("offers") or {}
    if isinstance(offers, dict):
        try:
            out["price_krw"] = int(float(offers.get("price") or 0))
        except (TypeError, ValueError):
            pass
    return out


def _parse_product(data: dict) -> dict:
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

    images = product.get("productImages") or product.get("images") or []
    if isinstance(images, list):
        for img in images:
            if isinstance(img, dict):
                u = img.get("url") or img.get("imageUrl") or ""
            elif isinstance(img, str):
                u = img
            else:
                u = ""
            if u and u.startswith("http"):
                if not out["cover_image_url"]:
                    out["cover_image_url"] = u
                out["extra_image_urls"].append(u)
    if not out["cover_image_url"]:
        out["cover_image_url"] = product.get("representImageUrl") or ""

    opts = product.get("optionCombinations") or product.get("options") or []
    if isinstance(opts, list):
        for o in opts[:30]:
            if isinstance(o, dict):
                name = o.get("optionName1") or o.get("name") or o.get("displayName") or ""
                if o.get("optionName2"):
                    name = f"{name} / {o.get('optionName2')}"
                price = int(o.get("price") or o.get("optionPrice") or out["price_krw"] or 0)
                in_stock = bool(o.get("stockQuantity", 1) > 0) if o.get("stockQuantity") is not None else True
                if name:
                    out["options"].append({"name": name, "price_krw": price, "in_stock": in_stock})

    delivery = product.get("productDeliveryInfo") or product.get("delivery") or {}
    if isinstance(delivery, dict):
        fee = delivery.get("baseFee") or delivery.get("deliveryFee")
        if fee:
            out["shipping_text"] = f"배송비 {fee:,}원"

    detail = product.get("detailContents") or []
    if isinstance(detail, list):
        for u in detail[:10]:
            if isinstance(u, str) and u.startswith("http"):
                out["extra_image_urls"].append(u)

    return out


async def _load_cookies(context):
    path = _cookies_path()
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as f:
            cookies = json.load(f)
        if cookies:
            await context.add_cookies(cookies)
            logger.info(f"[naver_fetch_v2] loaded {len(cookies)} cookies")
    except Exception as e:
        logger.warning(f"[naver_fetch_v2] cookies load fail: {e}")


async def _save_cookies(context):
    path = _cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cookies = await context.cookies()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        logger.info(f"[naver_fetch_v2] saved {len(cookies)} cookies")
    except Exception as e:
        logger.warning(f"[naver_fetch_v2] cookies save fail: {e}")


def _naver_profile_dir() -> Path:
    """CCCC-1 패턴: 영구 user-data-dir (사장님 1회 로그인 → 영구)."""
    p = Path(__file__).resolve().parent.parent.parent / "data" / "naver-browser-profile"
    p.mkdir(parents=True, exist_ok=True)
    return p


async def fetch_naver_url_v2(url: str, *, headless: bool = True, save_cookies: bool = True) -> dict:
    """URL → product info.

    R-8 (2026-05-02): 기본은 크롬 확장 (qoo10-helper-extension) 경유.
    환경변수 `EXT_USE_EXTENSION=false` 시 레거시 Playwright 흐름:
      1. 메인 Chrome 9222 attach (CDP) — 사장님 메인 Chrome 에 새 탭. 모든 로그인 활용.
      2. fallback: persistent context (별도 naver-browser-profile)

    레거시는 5/2 검증에서 5/5 모두 Naver 로그인 redirect 로 fail — 디스크 검사와
    실제 fetch 가 다른 프로필 보던 모순. R-8 확장은 메인 Chrome 1개 사용.
    """
    import os
    if os.getenv("EXT_USE_EXTENSION", "true").lower() == "true":
        from app.services.ext_client import fetch_one
        return await fetch_one(url)

    parsed = parse_naver_url(url)
    if not parsed:
        return {"error": "Naver smartstore/brand URL 아님"}

    from playwright.async_api import async_playwright

    pw = None
    context = None
    cdp_browser = None
    using_cdp = False
    try:
        pw = await async_playwright().start()

        # 1. 9222 attach 시도 (사장님 메인 Chrome)
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            cdp_alive = sock.connect_ex(("127.0.0.1", 9222)) == 0
            sock.close()
        except Exception:
            cdp_alive = False

        if cdp_alive:
            try:
                cdp_browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
                # 기본 context 사용 (사장님 메인 프로필 + 모든 cookies)
                if cdp_browser.contexts:
                    context = cdp_browser.contexts[0]
                    using_cdp = True
                    logger.info("[naver_fetch_v2] CDP attach 성공 — 사장님 메인 Chrome 사용")
            except Exception as e:
                logger.debug(f"[naver_fetch_v2] CDP attach fail (fallback): {e}")

        # 2. fallback — persistent context (별도 profile)
        if context is None:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(_naver_profile_dir()),
                headless=headless,
                executable_path=_chrome_exe(),
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1280,900",
                ],
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/147.0.0.0 Safari/537.36"
                ),
                locale="ko-KR",
                ignore_https_errors=True,
            )
            # 추가 cookies (cross-PC sync, 보조)
            await _load_cookies(context)

        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            return {"error": f"navigate fail: {e}"}

        # 로그인 redirect 감지 (Naver 가 로그인 요구 시)
        final_url = page.url
        title = (await page.title()) or ""
        if "nidlogin" in final_url or "로그인" in title:
            return {
                "error": (
                    "Naver 로그인 필요 — naver-browser-profile 에 로그인 cookies 없음. "
                    "해결: ① import_cookies_to_debug.bat 실행 (메인 Chrome 잠시 종료) "
                    "또는 ② headless=False 로 호출 후 직접 로그인"
                ),
                "redirect_url": final_url,
            }
        if "captcha" in title.lower() or "시스템점검" in title or "비정상" in title:
            return {"error": "captcha or block — headless=False 로 사장님 직접 풀어주면 cookies 저장됨"}

        html = await page.content()
        if save_cookies:
            await _save_cookies(context)

        # 1순위: JSON-LD (Naver smartstore 표준)
        ld = _extract_json_ld(html)
        if ld:
            info = _parse_json_ld(ld)
            # 상세 이미지 + 배송비 DOM 추출
            try:
                dom_extras = await page.evaluate("""
                    () => {
                        // detail content images
                        const imgs = document.querySelectorAll('div._3pZbN img, div[class*="detail"] img, div[class*="Detail"] img, div[class*="content"] img');
                        const detail_urls = Array.from(imgs).map(i => i.src).filter(s => s && s.startsWith('http'));

                        // 배송비 추출 — 우선순위:
                        // 1. 배송비 N원 (명시적 base 가격)
                        // 2. 단독 무료배송 (조건 없음)
                        // 3. 조건부 무료 → 무시 (base 가격 모름)
                        const all = document.body.innerText || '';
                        let shipping = '';
                        let base_krw = null;
                        let is_free = false;
                        let conditional_free = '';

                        // "배송비 3,000원" / "기본배송비 3,000원" / "택배배송 3,000원"
                        const mPrice = all.match(/(?:기본\\s*)?배송비\\s*([0-9,]+)\\s*원/);
                        // "N원 이상 무료" / "N원 이상 무료배송"
                        const mCondFree = all.match(/([0-9,]+)\\s*원\\s*이상\\s*무료(?:배송)?/);
                        // 단독 무료배송 — condition 없는
                        // (전체 text 에서 "무료배송" 만 등장하고 "이상" 없는 경우)
                        const allFreeMatches = all.match(/무료\\s*배송|무료배송|배송비\\s*무료/g) || [];
                        const condFreeMatches = all.match(/[0-9,]+\\s*원\\s*이상\\s*무료/g) || [];
                        const standaloneFree = allFreeMatches.length > condFreeMatches.length;

                        if (mPrice) {
                            base_krw = parseInt(mPrice[1].replace(/,/g, ''));
                            shipping = '배송비 ' + mPrice[1] + '원';
                        } else if (standaloneFree && !mCondFree) {
                            is_free = true;
                            shipping = '무료배송';
                            base_krw = 0;
                        }

                        if (mCondFree) {
                            conditional_free = mCondFree[1] + '원 이상 무료';
                            shipping += (shipping ? ' / ' : '') + conditional_free;
                        }

                        return {detail_urls, shipping, base_krw, is_free, conditional_free};
                    }
                """)
                if dom_extras:
                    detail_urls = dom_extras.get('detail_urls') or []
                    seen = set(info["extra_image_urls"])
                    for u in detail_urls[:30]:
                        if u not in seen:
                            info["extra_image_urls"].append(u)
                            seen.add(u)
                    # 배송비 DOM extracted (JSON-LD 의 빈 값 보완)
                    if dom_extras.get('shipping') and not info.get('shipping_text'):
                        info['shipping_text'] = dom_extras['shipping']
                    # base_krw 직접 사용 (개선된 로직 — 조건부 무료 ≠ 0원)
                    if dom_extras.get('base_krw') is not None:
                        info['shipping_krw'] = dom_extras['base_krw']
                    if dom_extras.get('conditional_free'):
                        info['conditional_free_text'] = dom_extras['conditional_free']
            except Exception:
                pass

            # fallback — shipping_text 에서 추출 (DOM 실패 시)
            if 'shipping_krw' not in info and info.get('shipping_text'):
                txt = info['shipping_text']
                # 단독 무료배송만 (조건부 제외)
                if '무료' in txt and '이상' not in txt:
                    info['shipping_krw'] = 0
                else:
                    m = re.search(r'(?:기본\s*)?배송비\s*([0-9,]+)\s*원', txt)
                    if m:
                        try:
                            info['shipping_krw'] = int(m.group(1).replace(',', ''))
                        except ValueError:
                            pass

            info["url"] = url
            info["mallName"] = parsed["mallName"]
            info["productId"] = parsed["productId"]
            info["title"] = title
            info["_source"] = "json-ld"
            return info

        # 2순위: __NEXT_DATA__
        data = _extract_next_data(html)
        if data:
            info = _parse_product(data)
            info["url"] = url
            info["mallName"] = parsed["mallName"]
            info["productId"] = parsed["productId"]
            info["title"] = title
            info["_source"] = "next-data"
            return info

        return {"error": "JSON-LD/NEXT_DATA 모두 없음"}
    finally:
        # CDP 모드면 page 만 close (Chrome browser 살려둠, 사장님 Chrome)
        # persistent context 모드면 context.close() (browser+context 종료)
        try:
            if 'page' in locals() and page and not page.is_closed():
                await page.close()
        except Exception:
            pass
        if not using_cdp:
            try:
                if context:
                    await context.close()
            except Exception:
                pass
        try:
            if pw:
                await pw.stop()
        except Exception:
            pass


__all__ = ["fetch_naver_url_v2", "parse_naver_url"]
