"""Chrome extension (qoo10-helper-extension) 큐 호출 클라이언트.

`naver_fetch_v2.fetch_naver_url_v2` 의 in-process 대체. backend 가 Playwright 로
직접 페이지 열지 않고, 사장님 메인 Chrome 의 확장에 작업을 위임한 뒤 결과를 수신.

흐름:
    fetch_one(url) → POST /api/ext/queue (1건)
                   → polling /api/ext/status?job_id=...
                   → completed 시 확장 결과 → naver_fetch_v2 호환 dict 으로 변환
                   → 반환

R-6 mode 에서는 사장님이 popup [즉시 폴링] 누르거나 alarm 1분 트리거 대기.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

# backend 가 자기 자신 호출 — 같은 process 같은 port
BACKEND_URL = "http://127.0.0.1:8000"

# 운영 default — settle 10초 + active tab 으로 hydration 끝까지 기다림
DEFAULT_CONFIG: dict[str, Any] = {
    "active_tab": True,
    "extract_detail_images": True,
    "max_detail_images": 15,
    "settle_ms": 10000,
    "delay_min_ms": 1000,
    "delay_max_ms": 1500,
}


async def fetch_one(
    url: str,
    *,
    keyword_jp: str | None = None,
    keyword_kr: str | None = None,
    timeout_seconds: int = 120,
    poll_interval: float = 2.0,
    config: dict | None = None,
) -> dict:
    """크롬 확장으로 1건 URL 추출 → naver_fetch_v2 호환 dict.

    timeout 초과 시 `{"error": "extension timeout"}`.
    확장이 실패 시 `{"error": "..."}`.
    """
    job_id = (
        f"single_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
    )
    cfg = {**DEFAULT_CONFIG, **(config or {})}

    item: dict[str, Any] = {"url": url}
    if keyword_jp:
        item["keyword_jp"] = keyword_jp
    if keyword_kr:
        item["keyword_kr"] = keyword_kr

    payload = {"job_id": job_id, "urls": [item], "config": cfg}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(f"{BACKEND_URL}/api/ext/queue", json=payload)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"[ext_client] queue register fail: {e}")
            return {"error": f"queue register fail: {e}"}

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            try:
                r = await client.get(
                    f"{BACKEND_URL}/api/ext/status",
                    params={"job_id": job_id},
                )
                r.raise_for_status()
                data = r.json()
                summary = data.get("summary") or {}
                status = summary.get("status")
                if status in ("completed", "failed"):
                    results = data.get("results") or {}
                    if not results:
                        return {"error": f"no result (status={status})"}
                    res = next(iter(results.values()))
                    if res.get("status") == "success":
                        return _to_naver_fetch_schema(res.get("data") or {})
                    return {"error": res.get("error") or "extension error"}
            except Exception as e:
                logger.warning(f"[ext_client] poll fail: {e}")
            await asyncio.sleep(poll_interval)

        return {"error": f"extension timeout after {timeout_seconds}s"}


def _to_naver_fetch_schema(ext_data: dict) -> dict:
    """확장 응답 → naver_fetch_v2 호환 dict.

    fetch_naver_url_v2 의 반환 키:
      product_name, price_krw, cover_image_url, options[],
      shipping_text, extra_image_urls[], weight_g, category_path, description
    """
    cover_imgs = list(ext_data.get("cover_images") or [])
    out = {
        "product_name": ext_data.get("product_name") or "",
        "price_krw": int(ext_data.get("price_krw") or 0),
        "cover_image_url": ext_data.get("cover_image_url") or "",
        "cover_images": cover_imgs,             # I (5/3): 썸네일 전체 — 다운로드 source
        "options": ext_data.get("options") or [],
        "shipping_text": "",
        "extra_image_urls": list(cover_imgs),    # 하위 호환 — 이미 cover_images 와 동일
        "weight_g": None,
        "category_path": ext_data.get("category_path") or "",
        "description": ext_data.get("description") or "",
        "_ext_source": ext_data.get("source"),
        "_ext_warnings": ext_data.get("_warnings") or [],
        "_ext_debug": ext_data.get("_debug") or {},
        "_ext_version": ext_data.get("extraction_version") or "",
    }
    # detail_image_urls 합침 (OCR/SEO 입력)
    for item in ext_data.get("detail_image_urls") or []:
        if isinstance(item, dict):
            u = item.get("url")
        elif isinstance(item, str):
            u = item
        else:
            u = None
        if u and u not in out["extra_image_urls"]:
            out["extra_image_urls"].append(u)

    # shipping_text 변환
    sh = ext_data.get("shipping") or {}
    if sh.get("kind") == "free":
        out["shipping_text"] = "무료배송"
    elif sh.get("kind") == "conditional":
        thr = sh.get("threshold") or 0
        out["shipping_text"] = f"조건부 무료 ({thr:,}원 이상)"
    elif sh.get("kind") == "paid" and sh.get("amount") is not None:
        out["shipping_text"] = f"배송비 {sh['amount']:,}원"

    return out
