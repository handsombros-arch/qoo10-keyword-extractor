"""비전 영역 — 상품 이미지 자동 평가 + 패키지 개수 카운트.

흐름:
    1) 비용 한도 체크 (BudgetExceededError 시 호출 스킵)
    2) PIL 로 max 1024px 리사이즈 → 임시 JPEG
    3) get_client_for("vision").chat_with_image(...)
    4) JSON 파싱 + 정규화

env: VISION_MODEL=gemini:gemini-2.5-flash (기본)
     또는 ollama:qwen2.5-vl:7b 같이 로컬 비전 모델

사용:
    score = await score_product_image_async("path.jpg", "03.뷰티&화장품")
    pkg = await count_packages_in_image_async("path.jpg")

    # sync 래퍼 (CLI/검증)
    score = score_product_image("path.jpg", "07.식품")
"""
from __future__ import annotations

import json
import logging
import re

from ._budget import BudgetExceededError, assert_budget_or_raise
from ._image_utils import cleanup_temp, resize_for_upload
from ._sync import run_sync
from .router import get_client_for, load_prompt

logger = logging.getLogger(__name__)


def _empty_score() -> dict:
    return {
        "is_package_front": 0.0,
        "is_content_visible": 0.0,
        "has_clutter": 0.0,
        "has_text_overlay": 0.0,
        "overall_score": 0.0,
        "note": "",
        "ok": False,
    }


def _empty_count() -> dict:
    return {"count": 0, "confidence": 0.0, "note": "", "ok": False}


def _parse_json(text: str) -> dict | None:
    """LLM JSON 응답 파싱 — 코드블록·머리말 제거 후 첫 { 부터 마지막 } 까지."""
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        out = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


def _clamp(v, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _overall(score: dict) -> float:
    """가중합 — 정면 + 내용물 가치 ↑, 잡요소·오버레이 ↓."""
    return (
        score.get("is_package_front", 0.0)
        + 0.5 * score.get("is_content_visible", 0.0)
        - 0.5 * score.get("has_clutter", 0.0)
        - 0.3 * score.get("has_text_overlay", 0.0)
    )


async def score_product_image_async(image_path: str, category: str = "기타") -> dict:
    """이미지를 4개 항목 0~1 점수로 평가. 실패 시 ok=False, 모두 0."""
    if not image_path:
        return _empty_score()

    try:
        await assert_budget_or_raise()
    except BudgetExceededError as e:
        logger.warning(f"[vision] {e}")
        out = _empty_score()
        out["note"] = f"BUDGET_EXCEEDED: {e}"
        return out

    try:
        client = get_client_for("vision")
    except Exception as e:
        logger.error(f"[vision] 클라이언트 생성 실패 ({e})")
        return _empty_score()

    template = load_prompt("image_scoring")
    prompt = template.replace("{category}", category or "기타")

    upload_path = resize_for_upload(image_path)
    try:
        result = await client.chat_with_image(
            [{"role": "user", "content": prompt}],
            [upload_path],
            temperature=0.0,
            json_mode=True,
            max_tokens=2048,  # Gemini 2.5 thinking 토큰 + JSON 응답 여유
        )
    except NotImplementedError as e:
        logger.error(f"[vision] 비전 미지원 모델: {e}")
        return _empty_score()
    except Exception as e:
        logger.error(f"[vision] 호출 실패 ({e})")
        return _empty_score()
    finally:
        cleanup_temp(upload_path, image_path)

    parsed = _parse_json(result.text)
    if not parsed:
        logger.warning(f"[vision] JSON 파싱 실패: {result.text[:120]!r}")
        return _empty_score()

    out = {
        "is_package_front": _clamp(parsed.get("is_package_front")),
        "is_content_visible": _clamp(parsed.get("is_content_visible")),
        "has_clutter": _clamp(parsed.get("has_clutter")),
        "has_text_overlay": _clamp(parsed.get("has_text_overlay")),
        "note": str(parsed.get("note") or "").strip(),
        "ok": True,
    }
    out["overall_score"] = round(_overall(out), 4)
    return out


async def count_packages_in_image_async(image_path: str) -> dict:
    """이미지의 동일 상품 패키지 개수 + confidence."""
    if not image_path:
        return _empty_count()

    try:
        await assert_budget_or_raise()
    except BudgetExceededError as e:
        logger.warning(f"[vision] {e}")
        out = _empty_count()
        out["note"] = f"BUDGET_EXCEEDED: {e}"
        return out

    try:
        client = get_client_for("vision")
    except Exception as e:
        logger.error(f"[vision] 클라이언트 생성 실패 ({e})")
        return _empty_count()

    template = load_prompt("package_counting")
    upload_path = resize_for_upload(image_path)
    try:
        result = await client.chat_with_image(
            [{"role": "user", "content": template}],
            [upload_path],
            temperature=0.0,
            json_mode=True,
            max_tokens=2048,
        )
    except NotImplementedError as e:
        logger.error(f"[vision] 비전 미지원 모델: {e}")
        return _empty_count()
    except Exception as e:
        logger.error(f"[vision] 호출 실패 ({e})")
        return _empty_count()
    finally:
        cleanup_temp(upload_path, image_path)

    parsed = _parse_json(result.text)
    if not parsed:
        logger.warning(f"[vision] JSON 파싱 실패: {result.text[:120]!r}")
        return _empty_count()

    try:
        count = int(parsed.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count < 0 or count > 999:
        count = 0

    return {
        "count": count,
        "confidence": _clamp(parsed.get("confidence")),
        "note": str(parsed.get("note") or "").strip(),
        "ok": True,
    }


def score_product_image(image_path: str, category: str = "기타") -> dict:
    """동기 래퍼 — CLI / 검증용."""
    return run_sync(score_product_image_async(image_path, category))


def count_packages_in_image(image_path: str) -> dict:
    """동기 래퍼 — CLI / 검증용."""
    return run_sync(count_packages_in_image_async(image_path))


__all__ = [
    "score_product_image",
    "score_product_image_async",
    "count_packages_in_image",
    "count_packages_in_image_async",
]
