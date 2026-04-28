"""두 상품 이미지 1:1 매칭 — 같은 상품인지 0~1 점수 + 사유.

흐름:
    1) 비용 한도 체크 (assert_budget_or_raise — vision.py 와 공유)
    2) 두 이미지 각각 PIL 리사이즈 → 임시 JPEG
    3) get_client_for("image_match").chat_with_image(images=[A, B])
    4) 두 가지 mix 옵션:
       (a) IMAGE_MATCH_ENSEMBLE  — 매번 두 모델 병렬 호출 + 결합 (avg/max/min)
       (b) IMAGE_MATCH_CASCADE   — 1차 점수 ≤ threshold 일 때만 2차 모델 재시도
                                   (false reject 보완, 정상 케이스는 1차만 — 비용 효율)
    5) JSON {score, note} 파싱

env:
    IMAGE_MATCH_MODEL=<provider:model>          (1차 모델, 예: ollama:minicpm-v:8b)
    IMAGE_MATCH_ENSEMBLE=<provider:model>       (선택, 매번 병렬)
    IMAGE_MATCH_ENSEMBLE_MODE=avg|max|min       (기본 avg)
    IMAGE_MATCH_CASCADE=<provider:model>        (선택, 1차 0점 케이스만 호출)
    IMAGE_MATCH_CASCADE_THRESHOLD=0.05          (1차 점수 이 값 이하면 2차 시도)
prompt: app/services/llm/prompts/image_matching.txt

사용:
    res = await compare_two_images_async("/q/cover.jpg", "/d/cover.jpg")
    # res = {"score": 0.85, "note": "동일 패키지", "ok": True}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from ._budget import BudgetExceededError, assert_budget_or_raise
from ._image_utils import cleanup_temp, resize_for_upload
from ._sync import run_sync
from .router import _build_client, get_client_for, load_prompt

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


async def _call_one_model(client, template: str, upload_a: str, upload_b: str) -> dict | None:
    """단일 모델 호출 — (parsed_dict | None)."""
    try:
        result = await client.chat_with_image(
            [{"role": "user", "content": template}],
            [upload_a, upload_b],
            temperature=0.0,
            json_mode=True,
            max_tokens=512,
        )
    except NotImplementedError as e:
        logger.error(f"[image_match] 비전 미지원 모델 ({client.name}): {e}")
        return None
    except Exception as e:
        logger.error(f"[image_match] 호출 실패 ({client.name}): {e}")
        return None
    return _parse_json(result.text)


def _combine_scores(scores: list[float], mode: str) -> float:
    if not scores:
        return 0.0
    if mode == "max":
        return max(scores)
    if mode == "min":
        return min(scores)
    return sum(scores) / len(scores)  # avg


async def compare_two_images_async(image_a: str, image_b: str) -> dict:
    """큐텐 cover (A) ↔ 한국 cover (B) 같은 상품인지 0~1 점수.

    빈 경로/누락 파일은 즉시 _empty() 반환.
    BudgetExceededError 발생 시 score=0, note="BUDGET_EXCEEDED".
    IMAGE_MATCH_ENSEMBLE 설정 시 두 모델 병렬 호출 + 결합.
    IMAGE_MATCH_CASCADE 설정 시 1차 점수 낮으면 2차 모델로 second-opinion.
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

    # 1차 — 기본 모델
    try:
        primary = get_client_for("image_match")
    except Exception as e:
        logger.error(f"[image_match] 클라이언트 생성 실패 ({e})")
        return _empty()

    # 2차 — ensemble 우선, 없으면 cascade
    ensemble_spec = (os.getenv("IMAGE_MATCH_ENSEMBLE") or "").strip()
    cascade_spec = (os.getenv("IMAGE_MATCH_CASCADE") or "").strip()
    secondary = None
    second_mode = None  # "ensemble" | "cascade" | None

    if ensemble_spec:
        try:
            secondary = _build_client(ensemble_spec)
            second_mode = "ensemble"
        except Exception as e:
            logger.warning(f"[image_match] ensemble {ensemble_spec} 빌드 실패: {e}")
    elif cascade_spec:
        try:
            secondary = _build_client(cascade_spec)
            second_mode = "cascade"
        except Exception as e:
            logger.warning(f"[image_match] cascade {cascade_spec} 빌드 실패: {e}")

    template = load_prompt("image_matching")
    upload_a = resize_for_upload(image_a)
    upload_b = resize_for_upload(image_b)

    try:
        if second_mode == "ensemble":
            # 두 모델 매번 병렬
            res_a, res_b = await asyncio.gather(
                _call_one_model(primary, template, upload_a, upload_b),
                _call_one_model(secondary, template, upload_a, upload_b),
                return_exceptions=False,
            )
            results = [r for r in (res_a, res_b) if r]
        else:
            # 1차만 우선 호출
            res1 = await _call_one_model(primary, template, upload_a, upload_b)
            results = [res1] if res1 else []
            # cascade — 1차 점수 ≤ threshold 면 2차 시도 (false reject 보완)
            if second_mode == "cascade" and secondary is not None:
                try:
                    cascade_threshold = float(os.getenv("IMAGE_MATCH_CASCADE_THRESHOLD") or "0.05")
                except ValueError:
                    cascade_threshold = 0.05
                first_score = _clamp((res1 or {}).get("score") or 0)
                if first_score <= cascade_threshold:
                    res2 = await _call_one_model(secondary, template, upload_a, upload_b)
                    if res2:
                        results.append(res2)
                        logger.info(
                            f"[image_match] cascade 발동 (1차={first_score:.2f} ≤ {cascade_threshold:.2f}) "
                            f"→ 2차={_clamp(res2.get('score')):.2f}"
                        )
    finally:
        cleanup_temp(upload_a, image_a)
        cleanup_temp(upload_b, image_b)

    if not results:
        return _empty()

    scores = [_clamp(r.get("score")) for r in results]
    notes = [str(r.get("note") or "").strip() for r in results if r.get("note")]

    if second_mode == "cascade" and len(scores) > 1:
        # cascade — 2차 점수 채택 (1차가 false reject 의심이라 호출했음)
        score = scores[1]
    elif second_mode == "ensemble":
        mode = (os.getenv("IMAGE_MATCH_ENSEMBLE_MODE") or "avg").lower()
        score = _combine_scores(scores, mode)
    else:
        score = scores[0]

    note = notes[0][:60] if notes else ""
    if len(notes) > 1 and notes[1] != notes[0]:
        note += f" | m2:{notes[1][:40]}"

    return {
        "score": round(score, 4),
        "note": note[:120],
        "ok": True,
        "ensemble": len(results) > 1,
        "second_mode": second_mode or "none",
        "individual_scores": scores,
    }


def compare_two_images(image_a: str, image_b: str) -> dict:
    """동기 래퍼 — CLI / 테스트용."""
    return run_sync(compare_two_images_async(image_a, image_b))


__all__ = ["compare_two_images", "compare_two_images_async"]
