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
    "배송비 무료", "택배 무료", "FREE",
)
_CONDITIONAL_RE = re.compile(
    r"(\d+(?:[,\.]\d{3})*)\s*원?\s*이상.*?(?:무료|free)",
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
    for kw in _FREE_KW:
        if kw.lower() in t.lower():
            return {"kind": "free", "amount": 0, "threshold": None}
    nums = [int(s.replace(",", "")) for s in re.findall(r"\d{1,3}(?:,\d{3})+", t)]
    if nums:
        return {"kind": "paid", "amount": min(nums), "threshold": None}
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


# ─── 네이버 (browser_manager 의 큐텐 컨텍스트에 새 탭) ──────


async def _fetch_naver_via_browser_manager(url: str) -> dict:
    """browser_manager 의 살아있는 큐텐 Chrome 컨텍스트에 새 탭 추가 → 한국 셀러 페이지 진입.

    헤드풀 + 큐텐 로그인 쿠키 (도메인 다르니 한국 쇼핑은 영향 X)
    + 사용자 GUI 환경 → 봇 탐지 우회.
    """
    out: dict[str, Any] = {
        "options": [], "shipping_text": "", "extra_image_urls": [],
    }
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
        await page.wait_for_timeout(2000)
        try:
            await page.mouse.wheel(0, 800)
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # 차단/에러 페이지
        title = (await page.title()) or ""
        if "에러" in title or "Error" in title:
            logger.warning(f"[detail/naver] 에러 페이지 (title={title!r})")
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

        # 옵션
        try:
            for sel in [
                "ul[class*='option'] li", "[class*='Option'] li",
                "select option",
            ]:
                els = page.locator(sel)
                cnt = await els.count()
                if cnt and cnt < 30:
                    cnt_added = 0
                    for i in range(cnt):
                        try:
                            t = (await els.nth(i).inner_text(timeout=1500)).strip()
                            if t and len(t) < 100:
                                price = _parse_int_krw(t)
                                if price and price != price_main:
                                    out["options"].append({
                                        "name": t[:80], "price_krw": price, "in_stock": True,
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
            "[class*='delivery']", "[class*='Delivery']",
            "[class*='shipping']", "[class*='Shipping']",
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
            parsed = await _fetch_coupang(product_url)
        else:
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
