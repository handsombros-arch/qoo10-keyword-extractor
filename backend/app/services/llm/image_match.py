"""두 상품 이미지 1:1 매칭 — 같은 상품인지 0~1 점수 + 사유.

흐름:
    1) 비용 한도 체크 (assert_budget_or_raise — vision.py 와 공유)
    2) 두 이미지 각각 PIL 리사이즈 → 임시 JPEG
    3) get_client_for("image_match").chat_with_image(images=[A, B])
    4) JSON {score, note} 파싱

env: IMAGE_MATCH_MODEL=<provider:model>  (기본 ollama:minicpm-v:8b)
prompt: app/services/llm/prompts/image_matching.txt

사용:
    res = await compare_two_images_async("/q/cover.jpg", "/d/cover.jpg")
    # res = {"score": 0.85, "note": "동일 패키지", "ok": True}
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


def _empty() -> dict:
    return {"score": 0.0, "note": "", "ok": False}


def _clamp(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0: return 0.0
    if f > 1.0: return 1.0
    return f


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return None


async def compare_two_images_async(image_a: str, image_b: str) -> dict:
    """큐텐 cover (A) ↔ 한국 cover (B) 같은 상품인지 0~1 점수.

    빈 경로/누락 파일은 즉시 _empty() 반환.
    BudgetExceededError 발생 시 score=0, note="BUDGET_EXCEEDED".
    """
    if not image_a or not image_b:
        return _empty()

    try:
        await assert_budget_or_raise()
    except BudgetExceededError as e:
        logger.warning(f"[image_match] {e}")
        out = _empty()
        out["note"] = f"BUDGET_EXCEEDED: {e}"
        return out

    try:
        client = get_client_for("image_match")
    except Exception as e:
        logger.error(f"[image_match] 클라이언트 생성 실패 ({e})")
        return _empty()

    template = load_prompt("image_matching")

    # 두 이미지 각각 리사이즈 (1024px 한도). 둘 다 임시 파일이면 cleanup.
    upload_a = resize_for_upload(image_a)
    upload_b = resize_for_upload(image_b)

    try:
        result = await client.chat_with_image(
            [{"role": "user", "content": template}],
            [upload_a, upload_b],
            temperature=0.0,
            json_mode=True,
            max_tokens=512,
        )
    except NotImplementedError as e:
        logger.error(f"[image_match] 비전 미지원 모델: {e}")
        return _empty()
    except Exception as e:
        logger.error(f"[image_match] 호출 실패 ({e})")
        return _empty()
    finally:
        cleanup_temp(upload_a, image_a)
        cleanup_temp(upload_b, image_b)

    parsed = _parse_json(result.text)
    if not parsed:
        logger.warning(f"[image_match] JSON 파싱 실패: {(result.text or '')[:120]!r}")
        return _empty()

    score = _clamp(parsed.get("score"))
    note = str(parsed.get("note") or "").strip()[:120]
    return {"score": round(score, 4), "note": note, "ok": True}


def compare_two_images(image_a: str, image_b: str) -> dict:
    """동기 래퍼 — CLI / 테스트용."""
    return run_sync(compare_two_images_async(image_a, image_b))


__all__ = ["compare_two_images", "compare_two_images_async"]
