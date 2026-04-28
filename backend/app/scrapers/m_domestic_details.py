"""한국 상품 상세 페이지 진입 — 옵션별 가격 + 배송비 + 추가 이미지.

분기 (사용자 힌트 2026-04-28):
    - 쿠팡 (coupang.com / link.coupang.com): Scrapling StealthyFetcher
      (m07_coupang.py 와 동일 패턴 — camoufox stealth Firefox 가 AKAMAI 우회 검증됨)
    - 네이버 (smartstore.naver.com 등): 기존 큐텐 로그인된 browser_manager 의
      Chrome 컨텍스트에 새 탭 추가 (큐텐 _page 그대로, ctx.new_page() 분리)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import Page

from app.services.domestic_image_pipeline import IMAGE_ROOT, _safe_folder_name

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\s*원)?")
_NUMERIC_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")

_FREE_KW = (
    "무료배송", "무료 배송", "무료셔틀", "Free shipping",
    "배송비 무료", "택배 무료", "FREE", "당일배송 무료",
    "오늘출발 무료", "익일도착 무료", "배송 무료",
    "전 상품 무료", "전상품 무료",
)
_CONDITIONAL_RE = re.compile(
    r"(\d+(?:[,\.]\d{3})*)\s*원?\s*이상.*?(?:무료|free)",
    re.IGNORECASE,
)
_CONDITIONAL_MAN_RE = re.compile(  # "5만원 이상 무료" 패턴
    r"(\d+)\s*만\s*원?\s*이상.*?(?:무료|free)",
    re.IGNORECASE,
)


def _parse_int_krw(s: str) -> int | None:
    if not s:
        return None
    m = _NUMERIC_RE.search(s)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_shipping(text: str) -> dict:
    """배송비 텍스트 → {kind, amount, threshold}."""
    if not text:
        return {"kind": "unknown", "amount": None, "threshold": None}
    t = text.strip()
    # 조건부 1: "20,000원 이상 무료"
    m = _CONDITIONAL_RE.search(t)
    if m:
        thr_str = m.group(1).replace(",", "").replace(".", "")
        try:
            threshold = int(thr_str)
            if threshold < 100 and "만원" in t:
                threshold *= 10000
            return {"kind": "conditional", "amount": 0, "threshold": threshold}
        except ValueError:
            pass
    # 조건부 2: "5만원 이상 무료"
    m2 = _CONDITIONAL_MAN_RE.search(t)
    if m2:
        try:
            threshold = int(m2.group(1)) * 10000
            return {"kind": "conditional", "amount": 0, "threshold": threshold}
        except ValueError:
            pass
    # 무료 (단순 키워드 매치)
    t_lower = t.lower()
    for kw in _FREE_KW:
        if kw.lower() in t_lower:
            return {"kind": "free", "amount": 0, "threshold": None}
    # 가격 명시 — 광고문구 노이즈 제거 후 가장 작은 정상 가격을 배송비로 채택
    nums = [int(s.replace(",", "")) for s in re.findall(r"\d{1,3}(?:,\d{3})+", t)]
    nums = [n for n in nums if 500 <= n <= 50000]  # 배송비 합리적 범위
    if nums:
        return {"kind": "paid", "amount": min(nums), "threshold": None}
    # "배송비 0원" 같은 단일 자리 0
    if re.search(r"배송비\s*[:0]?\s*0\s*원", t):
        return {"kind": "free", "amount": 0, "threshold": None}
    return {"kind": "unknown", "amount": None, "threshold": None}


# ─── 세션 ──────────────────────────────────────────────────


class DomesticDetailSession:
    """워커 단위 세션 — 셀러 분기 시 별도 launch 없음.

    쿠팡: Scrapling 은 호출당 fetch (세션 무관)
    네이버: 기존 browser_manager 의 page 를 빌려서 새 탭 추가

    __aenter__/__aexit__ 는 향후 캐시/통계용 빈 컨텍스트.
    """

    def __init__(self):
        self._korean_pages_opened = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass


# ─── 쿠팡 (Scrapling StealthyFetcher — m07 검증된 패턴) ────


def _stealth_fetch_coupang(url: str):
    """동기 — m07_coupang.py 와 동일 패턴, wait 길게."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as e:
        raise RuntimeError("scrapling 미설치") from e

    kwargs = {
        "headless": True,
        "network_idle": True,
        "google_search": True,
        "block_images": False,
        "humanize": True,
        "solve_cloudflare": True,
        "wait": 5000,
    }
    optional = ["solve_cloudflare", "humanize", "google_search"]
    for attempt in range(len(optional) + 1):
        try:
            return StealthyFetcher.fetch(url, **kwargs)
        except TypeError:
            if attempt < len(optional):
                kwargs.pop(optional[attempt], None)
            else:
                raise


def _text(node) -> str:
    if node is None:
        return ""
    for attr in ("text", "text_content"):
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


def _attr(node, key: str) -> str:
    if node is None:
        return ""
    try:
        attrib = getattr(node, "attrib", None)
        if attrib is not None:
            v = attrib.get(key) if hasattr(attrib, "get") else attrib[key]
            if v:
                return str(v).strip()
    except Exception:
        pass
    try:
        v = node[key]
        if v:
            return str(v).strip()
    except Exception:
        pass
    return ""


def _css_first(page, sel):
    try:
        els = page.css(sel)
    except Exception:
        return None
    items = list(els) if els is not None else []
    return items[0] if items else None


async def _fetch_coupang(url: str) -> dict:
    """쿠팡 vp/products + 옵션/배송비/이미지 (Scrapling StealthyFetcher)."""
    out: dict[str, Any] = {
        "options": [], "shipping_text": "", "extra_image_urls": [],
    }
    try:
        page = await asyncio.to_thread(_stealth_fetch_coupang, url)
    except Exception as e:
        logger.warning(f"[detail/coupang] fetch 실패 {url[:60]}: {e}")
        return out
    if page is None:
        return out

    # 차단 검사
    try:
        body_text = (page.text if hasattr(page, "text") else None) or ""
    except Exception:
        body_text = ""
    if isinstance(body_text, str) and "Access Denied" in body_text:
        logger.warning("[detail/coupang] Access Denied")
        return out

    # 가격 — selector + 정규식 fallback
    price_main = None
    for sel in [
        ".prod-price__sale .total-price strong",
        ".total-price strong",
        ".prod-price__price",
        "[class*='priceArea'] [class*='price']",
        "[class*='price'] strong",
    ]:
        el = _css_first(page, sel)
        if el:
            v = _parse_int_krw(_text(el))
            if v:
                price_main = v
                break
    if price_main is None:
        # Scrapling Response 에서 .body / .html_content / str() 로 HTML 추출
        try:
            html = ""
            for attr in ("html_content", "text"):
                v = getattr(page, attr, None)
                if isinstance(v, str):
                    html = v; break
                if callable(v):
                    r = v()
                    if isinstance(r, str): html = r; break
            if not html:
                html = str(page)
            nums = [int(s.replace(",", "")) for s in re.findall(r"\d{1,3}(?:,\d{3})+", html)]
            nums = [n for n in nums if 1000 <= n <= 10_000_000]
            if nums:
                price_main = Counter(nums).most_common(1)[0][0]
        except Exception:
            pass
    # OCR 폴백 (kc-cert-checker 패턴) — Scrapling 은 page.screenshot 없음, 추가 이미지 다운로드 X.
    # 쿠팡은 후속 작업에서 Playwright 헤드풀로 전환 시 OCR 적용.
    if price_main:
        out["options"].append({"name": "default", "price_krw": price_main, "in_stock": True})

    # 옵션 (li 텍스트 + 가격 정규식)
    try:
        for sel in [
            "ul[class*='prod-option'] li",
            "[class*='Option'] li",
            "select[class*='option'] option",
        ]:
            try:
                els = page.css(sel)
            except Exception:
                els = []
            opts_cnt = 0
            for el in list(els)[:20]:
                t = _text(el)
                if not t or len(t) > 100:
                    continue
                price = _parse_int_krw(t)
                if price and price != price_main:
                    out["options"].append({"name": t[:80], "price_krw": price, "in_stock": True})
                    opts_cnt += 1
            if opts_cnt:
                break
    except Exception:
        pass

    # 배송비
    ship_text = ""
    for sel in [
        ".prod-shipping-fee", ".shipping-fee",
        "[class*='shipping']", "[class*='Shipping']",
        "[class*='Delivery'] [class*='fee']",
    ]:
        try:
            els = page.css(sel)
        except Exception:
            els = []
        for el in list(els)[:3]:
            t = _text(el)
            if t and len(ship_text) < 200:
                ship_text += " " + t
    out["shipping_text"] = ship_text.strip()

    # 추가 이미지
    seen: set[str] = set()
    for sel in [
        ".prod-image img",
        "[class*='ProductImage'] img",
        "img[src*='coupangcdn.com']",
    ]:
        try:
            imgs = page.css(sel)
        except Exception:
            imgs = []
        for img in list(imgs)[:10]:
            src = _attr(img, "src") or _attr(img, "data-src")
            if src and src.startswith("http") and src not in seen:
                seen.add(src)
                out["extra_image_urls"].append(src)
            if len(out["extra_image_urls"]) >= 6:
                break
        if len(out["extra_image_urls"]) >= 6:
            break

    return out


# ─── 쿠팡 (browser_manager 헤드풀 + 검색→클릭) ────────────


async def _fetch_coupang_via_browser_manager(product_url: str, product_name: str = "") -> dict:
    """쿠팡 헤드풀 진입 — kc-cert-checker 패턴 (검색→클릭 + 2~4초 대기 + OCR 폴백).

    AKAMAI 우회 핵심: vp/products 직접 X, /np/search?q=상품명 → 자연스러운 클릭.
    browser_manager 의 큐텐 헤드풀 Chrome 컨텍스트에 새 탭 추가.
    """
    out: dict[str, Any] = {
        "options": [], "shipping_text": "", "extra_image_urls": [],
    }

    # ① 사용자 디버그 Chrome attach 시도
    pw_user, browser_user, ctx = await _get_user_chrome_context()
    using_cdp = ctx is not None
    bm_page = None

    # ② fallback — browser_manager
    if ctx is None:
        try:
            from app.browser.manager import browser_manager
            bm_page = await browser_manager.get_page()
            ctx = bm_page.context
        except Exception as e:
            logger.warning(f"[detail/coupang] browser_manager 획득 실패: {e}")
            return out

    page: Page | None = None
    try:
        page = await ctx.new_page()
        if not using_cdp:
            try:
                from tf_playwright_stealth import stealth_async
                await stealth_async(page)
            except Exception:
                pass

        # 1단계 — 검색 페이지 (정당한 진입)
        if product_name:
            from urllib.parse import quote
            search_url = f"https://www.coupang.com/np/search?q={quote(product_name[:80])}&channel=user"
            try:
                await page.goto(
                    search_url,
                    referer="https://www.google.com/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await page.wait_for_timeout(random.randint(2000, 4000))
                # 자연스러운 스크롤
                await page.mouse.wheel(0, random.randint(400, 800))
                await page.wait_for_timeout(random.randint(1000, 2000))
            except Exception as e:
                logger.warning(f"[detail/coupang] 검색 페이지 진입 실패: {e}")

        # 2단계 — 실제 product_url 진입 (검색 결과의 자연스러운 다음 페이지)
        try:
            await page.goto(
                product_url,
                referer=page.url or "https://www.coupang.com/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except Exception as e:
            logger.warning(f"[detail/coupang] goto 실패 {product_url[:60]}: {e}")
            return out
        try:
            await page.wait_for_timeout(random.randint(2000, 4000))
            await page.mouse.wheel(0, random.randint(600, 1200))
            await page.wait_for_timeout(random.randint(1000, 2000))
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
        except Exception:
            pass

        # 차단 검사
        title = (await page.title()) or ""
        if "Access Denied" in title:
            logger.warning(f"[detail/coupang] 차단 (title={title!r})")
            return out

        # 가격 — selector + HTML 정규식 + OCR 폴백
        price_main = None
        for sel in [
            ".prod-price__sale .total-price strong",
            ".total-price strong",
            ".prod-price__price",
            "[class*='priceArea'] [class*='price']",
            "[class*='price'] strong",
            "[data-coupang-display-price]",
        ]:
            try:
                el = page.locator(sel).first
                if await el.count():
                    txt = (await el.inner_text(timeout=2000)).strip()
                    v = _parse_int_krw(txt)
                    if v:
                        price_main = v
                        break
            except Exception:
                continue
        if price_main is None:
            try:
                html = await page.content()
                nums = [int(s.replace(",", "")) for s in re.findall(r"\d{1,3}(?:,\d{3})+", html)]
                nums = [n for n in nums if 1000 <= n <= 10_000_000]
                if nums:
                    price_main = Counter(nums).most_common(1)[0][0]
            except Exception:
                pass
        if price_main is None:
            try:
                screenshot = await page.screenshot(full_page=False, type="png")
                from app.services.ocr import ocr_image_async, extract_price_main
                ocr_text = await ocr_image_async(screenshot)
                if ocr_text:
                    price_main = extract_price_main(ocr_text)
                    if price_main:
                        logger.info(f"[detail/coupang] OCR 폴백 가격: {price_main}")
            except Exception as e:
                logger.warning(f"[detail/coupang] OCR 폴백 실패: {e}")
        if price_main:
            out["options"].append({"name": "default", "price_krw": price_main, "in_stock": True})

        # 옵션 — 1) 드롭다운 트리거 클릭 2) selector 확장 + 가격 없는 옵션도 폴백
        try:
            for trigger_sel in [
                "[class*='OptionSelect']", "[class*='option-select']",
                "button[class*='select']", "[role='combobox']",
            ]:
                try:
                    triggers = page.locator(trigger_sel)
                    tcnt = await triggers.count()
                    for ti in range(min(tcnt, 3)):
                        try:
                            await triggers.nth(ti).click(timeout=1500, force=True)
                            await page.wait_for_timeout(400)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        seen_opt_names: set[str] = set()
        try:
            for sel in [
                "ul[class*='prod-option'] li", "[class*='Option'] li",
                "select[class*='option'] option",
                "[role='listbox'] [role='option']",
                "[class*='SelectBox'] li", "[class*='OptionList'] li",
                "[class*='dropdown'] li",
            ]:
                els = page.locator(sel)
                cnt = await els.count()
                if not cnt or cnt > 50:
                    continue
                cnt_added = 0
                for i in range(cnt):
                    try:
                        t = (await els.nth(i).inner_text(timeout=1500)).strip()
                        t = re.sub(r"\s+", " ", t)
                        if not t or len(t) > 80:
                            continue
                        price = _parse_int_krw(t)
                        name = re.sub(r"\d{1,3}(?:,\d{3})+\s*원?", "", t)
                        name = re.sub(r"수량\s*(증가|감소)|판매가|배송비|품절|sold\s*out", "", name, flags=re.I).strip()[:60]
                        if not name or len(name) < 2:
                            continue
                        if name.lower() in {"옵션", "선택", "필수", "default", "옵션 선택", "옵션선택"}:
                            continue
                        norm = name.lower()
                        if norm in seen_opt_names:
                            continue
                        seen_opt_names.add(norm)
                        opt_price = price if (price and price >= 1000) else price_main
                        if opt_price:
                            out["options"].append({
                                "name": name, "price_krw": opt_price, "in_stock": True,
                            })
                            cnt_added += 1
                    except Exception:
                        pass
                if cnt_added:
                    break
        except Exception:
            pass

        # 배송비
        ship_text = ""
        for sel in [
            ".prod-shipping-fee", ".shipping-fee",
            "[class*='shipping']", "[class*='Shipping']",
            "[class*='Delivery'] [class*='fee']",
        ]:
            try:
                els = page.locator(sel)
                cnt = await els.count()
                for i in range(min(cnt, 3)):
                    t = (await els.nth(i).inner_text(timeout=1500)).strip()
                    if t and len(ship_text) < 200:
                        ship_text += " " + t
            except Exception:
                continue
        out["shipping_text"] = ship_text.strip()

        # 추가 이미지
        try:
            img_locs = page.locator(
                ".prod-image img, [class*='ProductImage'] img, img[src*='coupangcdn.com']"
            )
            cnt = await img_locs.count()
            seen: set[str] = set()
            for i in range(min(cnt, 10)):
                try:
                    src = await img_locs.nth(i).get_attribute("src")
                    if src and src.startswith("http") and src not in seen:
                        seen.add(src)
                        out["extra_image_urls"].append(src)
                    if len(out["extra_image_urls"]) >= 6:
                        break
                except Exception:
                    pass
        except Exception:
            pass

    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if using_cdp:
            try:
                if browser_user:
                    await browser_user.close()
            except Exception:
                pass
            try:
                if pw_user:
                    await pw_user.stop()
            except Exception:
                pass

    return out


# ─── 네이버 (browser_manager 의 큐텐 컨텍스트에 새 탭) ──────


async def _get_user_chrome_context(timeout_ms: int = 2000):
    """사용자가 launch_chrome_debug.bat 으로 띄운 디버그 Chrome 에 attach (CDP).

    9222 포트로 connect_over_cdp 시도. 실패 시 None 반환 → caller 가 fallback.

    이게 가장 강력한 봇 회피 — 사용자의 평소 Chrome (또는 별도 디버그 프로필) 의
    모든 쿠키/세션/플러그인을 그대로 사용. 차단(번호 입력 captcha) 시 사용자가
    그 창에서 직접 풀어주면 자동화 계속 진행.

    Returns:
        (browser, context) 튜플 또는 (None, None)
    """
    import os
    port = int(os.getenv("CHROME_DEBUG_PORT", "9222"))
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.connect_over_cdp(
                f"http://localhost:{port}", timeout=timeout_ms,
            )
        except Exception as e:
            logger.debug(f"[detail/cdp] 9222 포트 attach 실패 ({e}) — fallback")
            await pw.stop()
            return None, None, None
        # 첫 컨텍스트 (디버그 Chrome 의 default context) 사용
        if not browser.contexts:
            logger.warning("[detail/cdp] 컨텍스트 없음 — fallback")
            await browser.close()
            await pw.stop()
            return None, None, None
        ctx = browser.contexts[0]
        return pw, browser, ctx
    except Exception as e:
        logger.debug(f"[detail/cdp] 초기화 실패 ({e})")
        return None, None, None


async def _fetch_naver_via_browser_manager(url: str) -> dict:
    """한국 셀러 페이지 진입 — CDP attach 우선, fallback browser_manager.

    1) **사용자 디버그 Chrome (포트 9222) attach** — 가장 강력. 사용자가
       launch_chrome_debug.bat 띄워둔 상태면 그 Chrome 에 새 탭 추가.
       차단(captcha) 시 사용자가 직접 풀어주면 자동화 계속.
    2) Fallback: browser_manager 의 큐텐 Chrome ctx 새 탭 (kc 패턴).
    """
    out: dict[str, Any] = {
        "options": [], "shipping_text": "", "extra_image_urls": [],
    }

    # ① 사용자 디버그 Chrome attach 시도
    pw_user, browser_user, ctx = await _get_user_chrome_context()
    using_cdp = ctx is not None
    bm_page = None

    # ② fallback — browser_manager
    if ctx is None:
        try:
            from app.browser.manager import browser_manager
            bm_page = await browser_manager.get_page()
            ctx = bm_page.context
        except Exception as e:
            logger.warning(f"[detail/naver] browser_manager 획득 실패: {e}")
            return out

    page: Page | None = None
    try:
        page = await ctx.new_page()
        # CDP attach 인 경우 stealth 적용 X (사용자 실제 Chrome 이라 더 자연스러움)
        if not using_cdp:
            try:
                from tf_playwright_stealth import stealth_async
                await stealth_async(page)
            except Exception:
                pass
        try:
            await page.goto(
                url,
                referer="https://search.naver.com/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except Exception as e:
            logger.warning(f"[detail/naver] goto 실패 {url[:60]}: {e}")
            return out
        # 사용자 GUI 환경이면 차단 시 captcha 풀 시간 더 줌
        wait_ms = random.randint(3000, 5000) if using_cdp else random.randint(2000, 3000)
        await page.wait_for_timeout(wait_ms)
        try:
            await page.mouse.wheel(0, 800)
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        # 차단/에러 페이지
        title = (await page.title()) or ""
        if "에러" in title or "Error" in title:
            logger.warning(f"[detail/naver] 에러 페이지 (title={title!r}, cdp={using_cdp})")
            return out

        # 가격 — selector + HTML 정규식 fallback
        price_main = None
        for sel in [
            "strong[class*='price']", "div[class*='price'] strong",
            "[class*='Price'] strong", ".price em", "._1LY7DqCnwR strong",
        ]:
            try:
                el = page.locator(sel).first
                if await el.count():
                    txt = (await el.inner_text(timeout=2000)).strip()
                    v = _parse_int_krw(txt)
                    if v:
                        price_main = v
                        break
            except Exception:
                continue
        if price_main is None:
            try:
                html = await page.content()
                nums = [int(s.replace(",", "")) for s in re.findall(r"\d{1,3}(?:,\d{3})+", html)]
                nums = [n for n in nums if 1000 <= n <= 10_000_000]
                if nums:
                    price_main = Counter(nums).most_common(1)[0][0]
            except Exception:
                pass
        # OCR 폴백 — HTML 정규식도 실패 시 페이지 스크린샷 → EasyOCR (kc-cert-checker 패턴)
        if price_main is None:
            try:
                screenshot = await page.screenshot(full_page=False, type="png")
                from app.services.ocr import ocr_image_async, extract_price_main
                ocr_text = await ocr_image_async(screenshot)
                if ocr_text:
                    price_main = extract_price_main(ocr_text)
                    if price_main:
                        logger.info(f"[detail/naver] OCR 폴백으로 가격 추출: {price_main}")
            except Exception as e:
                logger.warning(f"[detail/naver] OCR 폴백 실패: {e}")
        if price_main:
            out["options"].append({"name": "default", "price_krw": price_main, "in_stock": True})

        # 옵션 — 1) 드롭다운 트리거 클릭으로 list 펼치기 (NAVER smartstore React)
        #         2) selector 확장 + 가격 없는 옵션도 option_name 으로 추가
        try:
            for trigger_sel in [
                "[class*='option_select_btn']", "[class*='OptionSelectBtn']",
                "[class*='dropdown']:not([class*='content']):not([class*='list'])",
                "button[class*='select']", "[role='combobox']",
            ]:
                try:
                    triggers = page.locator(trigger_sel)
                    tcnt = await triggers.count()
                    for ti in range(min(tcnt, 3)):
                        try:
                            await triggers.nth(ti).click(timeout=1500, force=True)
                            await page.wait_for_timeout(400)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        # 옵션 추출 — selector 후보 확장
        seen_opt_names: set[str] = set()
        try:
            for sel in [
                "ul[class*='option'] li", "[class*='Option'] li",
                "select option",
                "[role='listbox'] [role='option']",
                "[class*='SelectBox'] li", "[class*='Selectbox'] li",
                "[class*='option_list'] li", "[class*='OptionList'] li",
                "[class*='dropdown'] li",
            ]:
                els = page.locator(sel)
                cnt = await els.count()
                if not cnt or cnt > 50:
                    continue
                cnt_added = 0
                for i in range(cnt):
                    try:
                        t = (await els.nth(i).inner_text(timeout=1500)).strip()
                        t = re.sub(r"\s+", " ", t)
                        if not t or len(t) > 80:
                            continue
                        price = _parse_int_krw(t)
                        # 옵션명 정제 — 가격/수량 컨트롤 텍스트 제거
                        name = re.sub(r"\d{1,3}(?:,\d{3})+\s*원?", "", t)
                        name = re.sub(r"수량\s*(증가|감소)|판매가|배송비|품절|sold\s*out", "", name, flags=re.I).strip()[:60]
                        if not name or len(name) < 2:
                            continue
                        if name.lower() in {"옵션", "선택", "필수", "default", "옵션 선택", "옵션선택"}:
                            continue
                        norm = name.lower()
                        if norm in seen_opt_names:
                            continue
                        seen_opt_names.add(norm)
                        # 가격이 행에 명시 → 사용 / 없으면 base price 폴백 (옵션명만으로도 SKU 분리 가치)
                        opt_price = price if (price and price >= 1000) else price_main
                        if opt_price and opt_price != price_main:
                            out["options"].append({
                                "name": name, "price_krw": opt_price, "in_stock": True,
                            })
                            cnt_added += 1
                        elif opt_price:
                            # 가격 동일/미상 — option_name 만 다양화 (검수 시 사용자가 가격 채움)
                            out["options"].append({
                                "name": name, "price_krw": opt_price, "in_stock": True,
                            })
                            cnt_added += 1
                    except Exception:
                        pass
                if cnt_added:
                    break
        except Exception:
            pass

        # 배송비 — selector 풍부화 + dt/dd 패턴 + body fallback
        ship_text = ""
        for sel in [
            "[class*='delivery']", "[class*='Delivery']",
            "[class*='shipping']", "[class*='Shipping']",
            "[class*='ShippingFee']", "[class*='shipping_area']",
            "[class*='DeliveryInfo']", "[class*='delivery_info']",
            "[data-shp-area-code='delivery']",
            "dt:has-text('배송비') + dd",
            "th:has-text('배송비') + td",
            "[aria-label*='배송']",
        ]:
            try:
                els = page.locator(sel)
                cnt = await els.count()
                for i in range(min(cnt, 5)):
                    t = (await els.nth(i).inner_text(timeout=1500)).strip()
                    if t and len(ship_text) < 400:
                        ship_text += " " + t
            except Exception:
                continue
        # body fallback — selector 다 실패 시 본문에서 "배송" 부근만 추출
        if not ship_text or "무료" not in ship_text and "원" not in ship_text:
            try:
                body_html = await page.content()
                # "배송" 단어 ±150 chars 윈도우에서 키워드 검색
                for m in re.finditer(r"배송", body_html):
                    start = max(0, m.start() - 50)
                    end = min(len(body_html), m.end() + 150)
                    snippet = re.sub(r"<[^>]+>", " ", body_html[start:end])
                    snippet = re.sub(r"\s+", " ", snippet).strip()
                    if any(kw in snippet for kw in ["무료", "원", "이상"]):
                        ship_text += " " + snippet[:200]
                        if len(ship_text) > 600:
                            break
            except Exception:
                pass
        out["shipping_text"] = ship_text.strip()[:600]

        # 추가 이미지
        try:
            img_locs = page.locator(
                "img[src*='shop-phinf.pstatic.net'], "
                "img[src*='phinf.pstatic.net'], "
                "[class*='thumb'] img, [class*='Thumb'] img"
            )
            cnt = await img_locs.count()
            seen: set[str] = set()
            for i in range(min(cnt, 10)):
                try:
                    src = await img_locs.nth(i).get_attribute("src")
                    if src and src.startswith("http") and src not in seen:
                        seen.add(src)
                        out["extra_image_urls"].append(src)
                    if len(out["extra_image_urls"]) >= 6:
                        break
                except Exception:
                    pass
        except Exception:
            pass

    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        # CDP attach 였으면 browser/playwright cleanup (디버그 Chrome 자체는 살아있음)
        if using_cdp:
            try:
                if browser_user:
                    await browser_user.close()
            except Exception:
                pass
            try:
                if pw_user:
                    await pw_user.stop()
            except Exception:
                pass

    return out


# ─── 공개 API ─────────────────────────────────────────────


async def scrape_domestic_detail(
    *,
    session: DomesticDetailSession,
    domestic_id: int,
    source: str,
    product_url: str,
    product_name_kr: str,
    date_str: str,
) -> dict:
    """한 한국 상품 상세 진입 — 셀러별 fetch + DB 저장용 결과."""
    result: dict[str, Any] = {
        "ok": False,
        "options": [],
        "shipping": {"kind": "unknown", "amount": None, "threshold": None},
        "extra_image_urls": [],
        "extra_image_paths": [],
        "note": "",
    }
    if not product_url:
        result["note"] = "no_url"
        return result

    src = (source or "").lower()
    url_lower = product_url.lower()
    is_coupang = "coupang.com" in url_lower

    try:
        if is_coupang:
            # 쿠팡: kc 패턴 — Playwright 헤드풀 + 검색→클릭 + 2~4초 대기
            parsed = await _fetch_coupang_via_browser_manager(product_url, product_name_kr)
        else:
            # 네이버 / 외부 셀러: browser_manager 새 탭 + OCR 폴백
            parsed = await _fetch_naver_via_browser_manager(product_url)
    except Exception as e:
        logger.warning(f"[detail] {src} 스크래핑 실패 {product_url[:60]}: {e}")
        result["note"] = f"fetch_error:{type(e).__name__}"
        return result

    result["options"] = parsed.get("options", [])
    result["shipping"] = parse_shipping(parsed.get("shipping_text", ""))
    result["extra_image_urls"] = parsed.get("extra_image_urls", [])

    # 추가 이미지 다운로드
    if result["extra_image_urls"]:
        folder_name = _safe_folder_name(product_name_kr or f"product_{domestic_id}")
        extras_dir = IMAGE_ROOT / date_str / folder_name / "extras"
        try:
            extras_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[detail] extras dir 생성 실패: {e}")
        else:
            saved: list[str] = []
            async with httpx.AsyncClient(
                timeout=15.0,
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True,
            ) as client:
                for idx, url in enumerate(result["extra_image_urls"][:6], 1):
                    try:
                        r = await client.get(url)
                        if r.status_code != 200 or len(r.content) < 1000:
                            continue
                        dest = extras_dir / f"{src}_{domestic_id}_{idx}.jpg"
                        dest.write_bytes(r.content)
                        try:
                            rel = dest.relative_to(IMAGE_ROOT.parent).as_posix()
                        except ValueError:
                            rel = str(dest)
                        saved.append(rel)
                    except Exception:
                        continue
            result["extra_image_paths"] = saved

    result["ok"] = bool(result["options"]) or result["shipping"]["kind"] != "unknown"
    if not result["ok"] and not result["note"]:
        result["note"] = "empty_parse"
    return result


__all__ = ["scrape_domestic_detail", "parse_shipping", "DomesticDetailSession"]
