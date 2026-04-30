"""큐텐/한국 cover image → vision LLM 으로 한 줄 description 추출 (GGG-1).

목적:
  - 큐텐 cover 와 한국 cover 가 시각적으로 다르더라도 (작가/광고 사진 vs 실제 상품)
    같은 상품이면 description 이 비슷하게 → 매칭 정합도 향상
  - 또는 description text 비교로 image_match 점수 보조

env: VISION_MODEL (qwen2.5vl:7b 권장 — 한국어 양호)

사용:
    desc = await describe_cover_async("https://gd.image-qoo10.jp/.../g_100-w-st_g.jpg")
    # → "white skincare bottle with red label, anti-aging eye cream"
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# 큐텐 cover URL 사이즈 변환: g_100 (썸네일 100x100) → g_500 (5배)
_QOO10_SIZE_RE = re.compile(r"\.g_(\d+)-")


def to_large_qoo10_url(url: str, target_size: int = 500) -> str:
    """큐텐 cover URL g_{N} 패턴을 큰 사이즈로. 큐텐 외 도메인은 그대로."""
    if not url or "image-qoo10" not in url:
        return url
    return _QOO10_SIZE_RE.sub(f".g_{target_size}-", url)


async def _download_to_temp(url: str, timeout: float = 10.0) -> str | None:
    if not url or not url.startswith("http"):
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = await c.get(url)
            r.raise_for_status()
            data = r.content
    except Exception as e:
        logger.debug(f"[cover_describe] download fail {url[:60]}: {e}")
        return None
    if not data or len(data) < 200:
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.write(data); tmp.close()
    return tmp.name


_PROMPT = (
    "이 상품 이미지를 한 줄로 간결하게 설명해주세요. 다음 형식:\n"
    "[상품 종류] [브랜드 또는 색상] [핵심 특징]\n"
    "예: 'skincare cream tube, white with red label, 30ml'\n"
    "예: 'BTS member photocard, IVE Wonyoung, holographic'\n"
    "예: 'protein powder pouch, brown package, vanilla flavor'\n"
    "한국어/영문 혼용 OK. 30단어 이내. 다른 설명 없이 한 줄만."
)


async def describe_cover_async(image_url: str) -> str | None:
    """vision LLM 으로 cover description 추출.

    qoo10 URL 은 자동으로 g_500 큰 이미지로 변환.
    실패 시 None.
    """
    if not image_url:
        return None
    # 큐텐이면 큰 이미지로
    large_url = to_large_qoo10_url(image_url, target_size=500)

    tmp = await _download_to_temp(large_url)
    # 큐텐 g_500 다운 실패 시 원본 g_100 fallback
    if not tmp and large_url != image_url:
        tmp = await _download_to_temp(image_url)
    if not tmp:
        return None

    try:
        from app.services.llm.router import get_client_for
        try:
            client = get_client_for("image_match")  # VISION_MODEL 또는 IMAGE_MATCH_MODEL
        except Exception:
            return None

        result = await client.chat_with_image(
            [{"role": "user", "content": _PROMPT}],
            [tmp],
            temperature=0.0,
            max_tokens=128,
        )
        text = (result.text or "").strip()
        # 한 줄로 정리, 마크다운/quotation 제거
        text = re.sub(r"^['\"`]+|['\"`]+$", "", text)
        text = text.split("\n")[0].strip()[:300]
        return text or None
    except Exception as e:
        logger.warning(f"[cover_describe] LLM fail: {e}")
        return None
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass


__all__ = ["describe_cover_async", "to_large_qoo10_url"]
