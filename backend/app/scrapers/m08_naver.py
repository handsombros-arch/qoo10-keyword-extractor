"""M08: 네이버 쇼핑 검색 — 공식 검색 API + BGE-M3 임베딩 매칭.

네이버 검색 API (https://developers.naver.com/) 사용. 일 25,000건 무료.
Client ID / Secret 발급 후 backend/.env 에 추가:

    NAVER_CLIENT_ID=...
    NAVER_CLIENT_SECRET=...

흐름:
    1. display=100 으로 100건 받음
    2. BGE-M3 임베딩으로 keyword 와 의미 유사한 것만 통과 (threshold)
    3. 가격 낮은 순으로 상위 N개 채택
    임베딩 사용 불가 시(모델 미설치 등) fallback: 가격 낮은 순 그대로
"""
from __future__ import annotations

import os
import re
from datetime import date

import httpx

from app.scrapers.base import BaseScraper
from app.services.semantic_match import is_available as semantic_available, match_candidates


NAVER_API_URL = "https://openapi.naver.com/v1/search/shop.json"
_TAG_RE = re.compile(r"<[^>]+>")

# 임베딩 매칭 임계값 — 한국어 ↔ 한국어 매칭이라 0.55 부터 시작 (운영 데이터로 튜닝)
_SIM_THRESHOLD = float(os.getenv("NAVER_SIM_THRESHOLD", "0.55"))


def _strip_html(s: str) -> str:
    return _TAG_RE.sub("", s or "").strip()


# 네이버 쇼핑 API 가 쿠팡 등 외부 셀러는 link.coupang.com/re/... 같은 추적 URL 반환.
# 사장님이 시트에서 클릭 시 이상한 redirect URL 보임 → 실제 상품 URL 로 정규화.
_COUPANG_TRACK_RE = re.compile(r"link\.coupang\.com/re/.*?[?&]itemId=(\d+).*?[?&]vendorItemId=(\d+)")


def _normalize_naver_link(url: str) -> str:
    """추적 URL → 표준 상품 URL.

    쿠팡: link.coupang.com/re/...?itemId=X&vendorItemId=Y → www.coupang.com/vp/products/X?vendorItemId=Y
    네이버 / 그 외: 그대로
    """
    if not url:
        return url
    m = _COUPANG_TRACK_RE.search(url)
    if m:
        item_id, vendor_id = m.group(1), m.group(2)
        return f"https://www.coupang.com/vp/products/{item_id}?vendorItemId={vendor_id}"
    return url


class NaverShoppingScraper(BaseScraper):
    """M08: 네이버 쇼핑 검색 (공식 API + 의미 매칭)."""

    async def run(self, keyword: str, max_results: int = 30, **params) -> dict:
        task_id = self.tasks.create_task("네이버 쇼핑 검색", 1)
        self.tasks.start_task(task_id)

        client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
        client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()

        if not client_id or not client_secret:
            self.tasks.fail_task(task_id, "NAVER_CLIENT_ID / SECRET 미설정")
            return {
                "task_id": task_id,
                "products": [],
                "error": (
                    "환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 필요합니다. "
                    "https://developers.naver.com 에서 애플리케이션 등록 후 backend/.env 에 추가."
                ),
            }

        try:
            self.tasks.update_progress(task_id, 0, f"'{keyword}' 네이버 API 100건 호출")
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    NAVER_API_URL,
                    headers={
                        "X-Naver-Client-Id": client_id,
                        "X-Naver-Client-Secret": client_secret,
                    },
                    params={
                        "query": keyword,
                        "display": 100,   # API 최대치
                        "start": 1,
                        "sort": "sim",
                    },
                )
                if resp.status_code != 200:
                    msg = f"API {resp.status_code}: {resp.text[:200]}"
                    self.tasks.fail_task(task_id, msg)
                    return {"task_id": task_id, "products": [], "error": msg}
                data = resp.json()

            raw_items = data.get("items") or []
            # 카탈로그(price-comparison) 페이지 우선순위 강하게 낮춤 — mallName="네이버"
            # 또는 link 가 search.shopping.naver.com/catalog/. 이런 페이지는 옵션/배송
            # 진입이 막혀 후속 단계 (Phase 2 옵션 채움) 에서 dead-end.
            #
            # 해결: 동일 상품이 카탈로그 + 직접 셀러 양쪽 있을 때 직접 셀러 우선.
            # 카탈로그만 있는 경우엔 어쩔 수 없이 받음 (데이터 손실 회피).
            seller_items = []
            catalog_items = []
            for it in raw_items:
                mall = (it.get("mallName") or "").strip()
                link = (it.get("link") or "")
                is_catalog = (
                    mall == "네이버"
                    or "search.shopping.naver.com/catalog" in link
                )
                if is_catalog:
                    catalog_items.append(it)
                else:
                    seller_items.append(it)
            # 셀러 우선 → 카탈로그 보충 (max_results 못 채울 때만)
            items = seller_items + catalog_items
            if not items:
                self.tasks.complete_task(task_id, "0개 결과")
                return {"task_id": task_id, "products": []}

            # 1차: 임베딩 매칭으로 의미 유사한 것만 통과
            titles = [_strip_html(it.get("title", "")) for it in items]
            if semantic_available():
                self.tasks.update_progress(
                    task_id, 0,
                    f"'{keyword}' BGE-M3 매칭 ({len(titles)}건 → 의미 유사도 ≥ {_SIM_THRESHOLD})"
                )
                matches = match_candidates(keyword, titles, threshold=_SIM_THRESHOLD)
                kept_indices = {idx for idx, _ in matches}
                score_map = dict(matches)
                filtered = [(items[idx], score_map[idx]) for idx in kept_indices]
                semantic_used = True
            else:
                # fallback: 모두 통과
                filtered = [(it, 0.0) for it in items]
                semantic_used = False

            # 2차: 가격 낮은 순 정렬 (의미 일치 그룹 안에서)
            def _lprice(item_score):
                v = item_score[0].get("lprice", "")
                try:
                    return int(v) if v else 0
                except (TypeError, ValueError):
                    return 0

            filtered_priced = [t for t in filtered if _lprice(t) > 0]
            filtered_priced.sort(key=_lprice)

            # 3차: 상위 max_results 개 채택
            chosen = filtered_priced[:max_results]

            products: list[dict] = []
            today = date.today()
            for it, score in chosen:
                try:
                    name = _strip_html(it.get("title", ""))
                    if not name:
                        continue
                    lprice = it.get("lprice", "")
                    try:
                        price_krw = int(lprice) if lprice else 0
                    except (TypeError, ValueError):
                        price_krw = 0
                    products.append({
                        "source": "naver",
                        "search_keyword": keyword,
                        "product_name": name,
                        "price_krw": price_krw,
                        "shipping_fee": "",
                        "origin": "",
                        "cover_image_url": it.get("image", ""),
                        "product_url": _normalize_naver_link(it.get("link", "")),
                        "lookup_date": today,
                    })
                except Exception:
                    continue

            verb = "임베딩 매칭" if semantic_used else "fallback"
            self.tasks.complete_task(
                task_id,
                f"{len(products)}개 채택 ({len(items)}→{len(filtered)} {verb} → 가격순 top {max_results})",
            )
            return {"task_id": task_id, "products": products}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e), "products": []}
