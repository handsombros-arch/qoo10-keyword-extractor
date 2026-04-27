"""한국 상품 상세 페이지 진입 — 옵션별 가격 + 배송비 + 추가 이미지.

대상: 매칭된 (DomesticMatchCandidate.decision='accepted') 한국 상품의 product_url.

흐름:
    1) 쿠팡: Scrapling StealthyFetcher 로 상세 페이지 HTML 획득 (AKAMAI 우회)
    2) 네이버: product_url 이 외부 셀러 사이트 — best-effort httpx GET
    3) 옵션 셀렉트 추출 (있으면) — 셀렉트 옵션 텍스트 + 가격 매핑
       1차 단순화: 단일 가격이면 단일 옵션 ("default"/price_krw) 1건만 저장.
       옵션 클릭 후 가격 변동 캡처는 후속 단계.
    4) 배송비 텍스트 + 정규식 → shipping_kind/amount/threshold
    5) 추가 이미지 URL 리스트 (상세 갤러리) → image/{date}/{name}/extras/ 에 저장

반환:
    {
      "ok": bool,
      "options": [{"name": str, "price_krw": int, "in_stock": bool}, ...],
      "shipping": {"kind": "free"|"paid"|"conditional"|"unknown", "amount": int, "threshold": int},
      "extra_image_urls": [url, ...],
      "extra_image_paths": [local_path, ...],
      "note": str,
    }
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from app.services.domestic_image_pipeline import IMAGE_ROOT, _safe_folder_name

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\s*원)?")
_NUMERIC_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")

# 배송비 키워드
_FREE_KW = (
    "무료배송", "무료 배송", "무료셔틀", "Free shipping", "배송비 무료",
    "택배 무료", "FREE",
)
_CONDITIONAL_RE = re.compile(
    r"(\d+(?:\,\d{3})*)\s*원?\s*이상.*(?:무료|free)",
    re.IGNORECASE,
)


def _parse_int_krw(s: str) -> int | None:
    """'2,500원' / '2500' / 'KRW 2,500' → 2500."""
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
    """상세 페이지의 배송비 텍스트 → {kind, amount, threshold}.

    우선순위: 조건부 (이상 무료) → 무료 키워드 → 가격 텍스트 (paid) → unknown.
    """
    if not text:
        return {"kind": "unknown", "amount": None, "threshold": None}
    t = text.strip()

    # 1) 조건부 무료 — "5만원 이상 무료" / "50,000원 이상 무료배송"
    m = _CONDITIONAL_RE.search(t)
    if m:
        thr_str = m.group(1).replace(",", "")
        try:
            threshold = int(thr_str)
            # "5만원" 같이 만원 단위면 *10000
            if threshold < 100 and "만원" in t:
                threshold *= 10000
            return {"kind": "conditional", "amount": 0, "threshold": threshold}
        except ValueError:
            pass

    # 2) 무료 키워드
    for kw in _FREE_KW:
        if kw.lower() in t.lower():
            return {"kind": "free", "amount": 0, "threshold": None}

    # 3) 유료 가격 (가격 패턴 발견 — 최저값 채택)
    nums = [
        int(s.replace(",", ""))
        for s in re.findall(r"\d{1,3}(?:,\d{3})+", t)
    ]
    if nums:
        return {"kind": "paid", "amount": min(nums), "threshold": None}

    return {"kind": "unknown", "amount": None, "threshold": None}


# ─── 쿠팡 상세 ─────────────────────────────────────────────


def _stealth_fetch_coupang(url: str):
    """동기. Scrapling StealthyFetcher 로 쿠팡 상세 HTML 획득."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as e:
        raise RuntimeError("scrapling 미설치") from e

    kwargs = {
        "headless": True,
        "network_idle": True,
        "google_search": True,
        "block_images": False,  # 상세 이미지 URL 추출 위해 이미지 허용
        "humanize": True,
        "solve_cloudflare": True,
        "wait": 4000,
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
    """page.css(sel) 첫 번째 요소 (Scrapling Response 호환)."""
    try:
        els = page.css(sel)
    except Exception:
        return None
    items = list(els) if els is not None else []
    return items[0] if items else None


def _extract_coupang_detail(page) -> dict:
    """쿠팡 상품 상세 페이지에서 옵션/배송/이미지 추출."""
    out: dict[str, Any] = {
        "options": [],
        "shipping_text": "",
        "extra_image_urls": [],
    }

    # 1) 가격 (메인) — .prod-price__sale .total-price strong
    price_main = None
    for sel in [
        ".prod-price__sale .total-price strong",
        ".total-price strong",
        ".prod-price__price",
        "[class*='priceArea'] [class*='price']",
    ]:
        el = _css_first(page, sel)
        if el:
            txt = _text(el)
            v = _parse_int_krw(txt)
            if v:
                price_main = v
                break
    if price_main:
        out["options"].append({
            "name": "default",
            "price_krw": price_main,
            "in_stock": True,
        })

    # 2) 배송비 영역 — '.prod-shipping-fee' / '.shipping-fee' / 배송 관련 텍스트
    shipping_text = ""
    for sel in [
        ".prod-shipping-fee", ".shipping-fee",
        "[class*='shipping']", "[class*='Shipping']",
    ]:
        try:
            els = page.css(sel)
        except Exception:
            els = []
        for el in list(els)[:3]:
            t = _text(el)
            if t and len(shipping_text) < 200:
                shipping_text += " " + t
    out["shipping_text"] = shipping_text.strip()

    # 3) 상세 이미지 — img[src*='thumbnail'] 또는 .prod-image img
    seen: set[str] = set()
    for sel in [
        ".prod-image img", "[class*='ProductImage'] img",
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


# ─── 네이버 상세 (best-effort) ────────────────────────────


async def _fetch_naver_detail(url: str) -> dict:
    """네이버 product_url → 외부 셀러 사이트. best-effort httpx GET.

    네이버 쇼핑은 셀러 페이지가 너무 다양해 일반화 어렵다. 1차는
    HTML 텍스트에서 가격/배송비 정규식만 시도. 실패 시 빈 결과.
    """
    out: dict[str, Any] = {
        "options": [], "shipping_text": "", "extra_image_urls": [],
    }
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            html = resp.text
    except Exception as e:
        logger.warning(f"[detail/naver] fetch 실패 {url[:60]}: {e}")
        return out

    # 가격 — 첫 번째 큰 가격 텍스트 (정규식)
    prices = [
        int(s.replace(",", ""))
        for s in re.findall(r"\d{1,3}(?:,\d{3})+", html)
    ]
    # 너무 큰 값(100만 이상) + 너무 작은 값 필터
    prices = [p for p in prices if 1000 <= p <= 1_000_000]
    if prices:
        # 가장 빈번한 값 — 메인 가격일 가능성 (셀러 페이지에서 같은 가격이 여러 곳 표기)
        from collections import Counter
        top = Counter(prices).most_common(1)[0][0]
        out["options"].append({"name": "default", "price_krw": top, "in_stock": True})

    # 배송비 — 무료/유료/조건부 텍스트 검색
    for chunk in re.findall(r".{0,50}(?:배송|무료|delivery|shipping).{0,80}", html, re.IGNORECASE):
        out["shipping_text"] += " " + chunk
        if len(out["shipping_text"]) > 500:
            break
    out["shipping_text"] = out["shipping_text"].strip()[:500]

    return out


# ─── 공개 API ─────────────────────────────────────────────


async def scrape_domestic_detail(
    *,
    domestic_id: int,
    source: str,             # "coupang" | "naver"
    product_url: str,
    product_name_kr: str,
    date_str: str,
) -> dict:
    """한 한국 상품의 상세 페이지 진입 + 옵션/배송/이미지 추출 + 로컬 이미지 저장.

    실패해도 자동화 막지 않음: ok=False + note.
    """
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
    # URL 호스트로 실제 분기 결정 — naver 검색 결과의 product_url 이
    # link.coupang.com / coupang.com 으로 redirect 되는 경우 다수.
    url_lower = product_url.lower()
    is_coupang_url = "coupang.com" in url_lower
    try:
        if is_coupang_url or src == "coupang":
            page = await asyncio.to_thread(_stealth_fetch_coupang, product_url)
            if page is None:
                result["note"] = "coupang_fetch_none"
                return result
            parsed = _extract_coupang_detail(page)
        elif src == "naver":
            parsed = await _fetch_naver_detail(product_url)
        else:
            result["note"] = f"unsupported_source:{src}"
            return result
    except Exception as e:
        logger.warning(f"[detail] {src} 스크래핑 실패 {product_url[:60]}: {e}")
        result["note"] = f"fetch_error:{type(e).__name__}"
        return result

    result["options"] = parsed.get("options", [])
    result["shipping"] = parse_shipping(parsed.get("shipping_text", ""))
    result["extra_image_urls"] = parsed.get("extra_image_urls", [])

    # 추가 이미지 다운로드 → image/{date}/{name}/extras/{idx}.jpg
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


__all__ = ["scrape_domestic_detail", "parse_shipping"]
