"""큐텐 일본 단품 페이지 → 가격 + 배송비 추출 (R, 5/3).

사용처: 상품 시트의 [컨텐츠 제작] 흐름 — 사장님이 큐텐 URL 채워두면
백엔드가 페이지 진입해서 경쟁가/경쟁배송 자동 입력.

browser_manager 의 persistent context 사용 (사장님 큐텐 로그인 활용).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.browser.manager import browser_manager

logger = logging.getLogger(__name__)


def _parse_yen(text: str) -> int | None:
    """'2,211円' / '￥1,500' / '300円 ~' / '300엔 ~' / '無料' → int (yen) 또는 None.

    "300円 ~" 같이 "~" 가 붙으면 base 가격 (300) 만 추출.
    """
    if not text:
        return None
    t = text.replace("\xa0", " ").strip()
    if any(k in t for k in ("無料", "free", "FREE", "送料無料", "무료배송")):
        return 0
    m = re.search(r"([\d,]{2,})", t)
    if not m:
        return None
    try:
        n = int(m.group(1).replace(",", ""))
        if 1 <= n <= 10_000_000:
            return n
    except ValueError:
        return None
    return None


async def fetch_qoo10_product_url(url: str) -> dict[str, Any]:
    """큐텐 단품 페이지 (`qoo10.jp/g/...`) → 가격 + 배송비.

    Returns:
        {price_jpy, shipping_jpy, source, error?}
    """
    if not url or "qoo10.jp" not in url.lower():
        return {"error": "qoo10.jp URL 아님"}

    if not browser_manager._is_alive():
        try:
            await browser_manager.initialize()
        except Exception as e:
            return {"error": f"browser_manager init 실패: {e}"}

    ctx = browser_manager._context
    if not ctx:
        return {"error": "browser_manager context 없음"}

    page = None
    try:
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1500)

        # 차단 검사
        title = (await page.title()) or ""
        if any(k in title.lower() for k in ("access denied", "blocked", "captcha")):
            return {"error": f"qoo10 차단 (title={title[:40]!r})"}

        # 가격 — 다양한 셀렉터 시도
        price = None
        for sel in [
            "strong.price_real",
            "#price strong",
            ".prc strong",
            "span#spnFinalPrice",
            "span#spnGdPrice",
            "[id*='spnPrice'] strong",
            "[class*='final_price']",
            "[class*='Price'] strong",
            ".prdt_price strong",
            ".price_big",
        ]:
            try:
                el = page.locator(sel).first
                if await el.count():
                    txt = (await el.inner_text(timeout=2000)).strip()
                    v = _parse_yen(txt)
                    if v and v >= 100:
                        price = v
                        break
            except Exception:
                continue

        # 가격 폴백 — HTML 정규식 (가장 흔한 ¥숫자 패턴)
        if price is None:
            try:
                html = await page.content()
                # 円 패턴
                yens = re.findall(r"([\d,]{3,})\s*円", html)
                nums = []
                for y in yens:
                    try:
                        n = int(y.replace(",", ""))
                        if 100 <= n <= 1_000_000:
                            nums.append(n)
                    except ValueError:
                        pass
                if nums:
                    # 가장 빈도 높은 값 = 메인 가격
                    from collections import Counter
                    price = Counter(nums).most_common(1)[0][0]
            except Exception:
                pass

        # 배송비 — 큐텐 일본 페이지 형식: "送料Overseas KSE(船便) - 300円 ~"
        # 1) JS evaluate 로 페이지 텍스트 전체에서 송료/우송료/KSE/Overseas 인근 가격 추출
        shipping = None
        try:
            ship_data = await page.evaluate(r"""
            () => {
              const out = { lines: [], matched: null };
              const re = /(送料|우송료|shipping|배송)[\s\S]{0,200}/i;
              for (const el of document.querySelectorAll('body *')) {
                if (el.children.length > 0) continue;
                const t = (el.innerText || '').trim();
                if (!t || t.length > 300) continue;
                if (re.test(t)) out.lines.push(t);
                if (out.lines.length >= 30) break;
              }
              return out;
            }
            """)
            lines = (ship_data or {}).get("lines") or []
            for line in lines:
                # "無料" / "送料無料" 우선
                if any(k in line for k in ("無料", "送料無料", "무료배송")):
                    shipping = 0
                    break
                # "300円" / "1,500円" 또는 "300엔" 패턴 — KSE/Overseas/船便 키워드 인근
                # "300円 ~" 의 "~" 는 무시하고 base 만
                m = re.search(r"([\d,]{2,})\s*(?:円|엔)", line)
                if m:
                    try:
                        n = int(m.group(1).replace(",", ""))
                        if 50 <= n <= 50_000:  # 합리적 배송비 범위
                            shipping = n
                            break
                    except ValueError:
                        pass
        except Exception as e:
            logger.debug(f"[qoo10_fetch] shipping JS evaluate 실패: {e}")

        # 2) selector 폴백 (옛 페이지 호환)
        if shipping is None:
            for sel in [
                "[class*='ship'] strong",
                "[class*='Ship'] strong",
                "[id*='ship'] strong",
                ".delivery_fee",
                "[class*='Delivery']",
                "td.shipping_fee",
                "span#spnShipPrice",
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count():
                        txt = (await el.inner_text(timeout=2000)).strip()
                        v = _parse_yen(txt)
                        if v is not None:
                            shipping = v
                            break
                except Exception:
                    continue

        # 옵션 추출 (S, 5/3) — 드롭다운 트리거 후 select / li 순회
        options: list[dict] = []
        try:
            # 1) 드롭다운 트리거 (없으면 안 눌러도 OK)
            for trigger_sel in [
                "[class*='option_select']",
                "[id*='option'] button",
                "select[id*='option']",
                "[role='combobox']",
            ]:
                try:
                    triggers = page.locator(trigger_sel)
                    cnt = await triggers.count()
                    for i in range(min(cnt, 3)):
                        try:
                            await triggers.nth(i).click(timeout=1200, force=True)
                            await page.wait_for_timeout(350)
                        except Exception:
                            pass
                except Exception:
                    pass

            # 2) select option 형식 (일반적)
            seen_names: set[str] = set()
            for sel in [
                "select[id*='option'] option",
                "select[name*='option'] option",
                "[id*='goodsOption'] option",
            ]:
                try:
                    els = page.locator(sel)
                    cnt = await els.count()
                    if cnt == 0 or cnt > 80:
                        continue
                    for i in range(cnt):
                        try:
                            txt = (await els.nth(i).inner_text(timeout=1500)).strip()
                            if not txt or len(txt) > 100:
                                continue
                            # 첫 옵션이 "選択してください" 같으면 스킵
                            if txt.startswith(("選択", "옵션", "필수", "----", "===")):
                                continue
                            v = _parse_yen(txt)  # 옵션 표기 안에 가격 있을 수 있음
                            name = re.sub(r"[\(\[]?\+?\s*[\d,]+\s*円\s*[\)\]]?", "", txt).strip()
                            if not name or len(name) < 2:
                                continue
                            norm = name.lower()
                            if norm in seen_names:
                                continue
                            seen_names.add(norm)
                            options.append({
                                "name": name[:80],
                                "price_jpy": v if v is not None else (price or 0),
                                "in_stock": True,
                            })
                        except Exception:
                            pass
                    if options:
                        break
                except Exception:
                    continue

            # 3) li / div 형식 폴백
            if not options:
                for sel in [
                    "ul[class*='option'] li",
                    "[class*='option_list'] li",
                    "[role='listbox'] [role='option']",
                ]:
                    try:
                        els = page.locator(sel)
                        cnt = await els.count()
                        if cnt == 0 or cnt > 60:
                            continue
                        for i in range(cnt):
                            try:
                                txt = (await els.nth(i).inner_text(timeout=1500)).strip()
                                if not txt or len(txt) > 100:
                                    continue
                                v = _parse_yen(txt)
                                name = re.sub(r"[\(\[]?\+?\s*[\d,]+\s*円\s*[\)\]]?", "", txt).strip()
                                if not name or len(name) < 2:
                                    continue
                                norm = name.lower()
                                if norm in seen_names:
                                    continue
                                seen_names.add(norm)
                                options.append({
                                    "name": name[:80],
                                    "price_jpy": v if v is not None else (price or 0),
                                    "in_stock": True,
                                })
                            except Exception:
                                pass
                        if options:
                            break
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"[qoo10_fetch] option extract 실패: {e}")

        # Cover 이미지 URL 추출 — og:image / 메인 thumb 셀렉터
        cover_url: str | None = None
        try:
            # 1) og:image meta (가장 안정적)
            try:
                og = page.locator("meta[property='og:image']").first
                if await og.count():
                    cover_url = (await og.get_attribute("content")) or None
            except Exception:
                pass
            # 2) 메인 상품 이미지 셀렉터 폴백
            if not cover_url:
                for sel in [
                    "img#objImgMain",
                    "img.gd_img_main",
                    "[id*='ImgMain'] img",
                    "[class*='gd_img'] img",
                    ".prdImg img",
                    "img[class*='product_img']",
                ]:
                    try:
                        el = page.locator(sel).first
                        if await el.count():
                            src = (await el.get_attribute("src")) or ""
                            if src and src.startswith(("http://", "https://", "//")):
                                cover_url = "https:" + src if src.startswith("//") else src
                                break
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"[qoo10_fetch] cover extract 실패: {e}")

        if price is None and shipping is None and not options and not cover_url:
            return {"error": "가격/배송/옵션/커버 모두 추출 실패", "title": title[:60]}

        return {
            "price_jpy": price,
            "shipping_jpy": shipping if shipping is not None else 0,
            "options": options,
            "cover_image_url": cover_url,
            "source": "qoo10_browser_manager",
        }
    except Exception as e:
        logger.warning(f"[qoo10_fetch] {url[:60]} 실패: {e}")
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        if page is not None:
            try: await page.close()
            except Exception: pass
