"""비전 파이프라인 — 여러 이미지 평가 후 베스트 선별 + 세트 개수 검증.

흐름:
    select_best_images: 이미지 N개 → 각 score → 정면 베스트 1장 + 내용물 베스트 1장
    verify_set_count:   이미지 + 기대 개수 → 이미지로 측정한 개수와 비교 → 권장 액션
"""
from __future__ import annotations

import asyncio
import logging

from ._sync import run_sync
from .vision import (
    count_packages_in_image_async,
    score_product_image_async,
)

logger = logging.getLogger(__name__)

# 카테고리별 best_content 시도 여부
_CONTENT_CATEGORIES = {"03.뷰티&화장품", "07.식품"}

# verify_set_count 의 confidence 임계값
_VERIFY_CONF_HIGH = 0.8


def _wants_content(category: str) -> bool:
    return (category or "").strip() in _CONTENT_CATEGORIES


async def select_best_images_async(
    image_paths: list[str],
    category: str = "기타",
) -> dict:
    """N개 이미지를 점수 매겨 정면/내용물 베스트 1장씩 반환.

    반환:
        {
            "best_package": str | None,
            "best_content": str | None,   # 화장품/식품만 시도
            "all_scores": list[dict],     # path 와 score 를 함께
        }

    비용 한도 초과로 일부 호출이 실패해도 가능한 만큼 평가.
    """
    paths = [p for p in (image_paths or []) if p]
    if not paths:
        return {"best_package": None, "best_content": None, "all_scores": []}

    # 동시 호출은 1로 (Gemini 무료 티어 분당 한도 + 비전 무거움). 순차로 진행.
    scores: list[dict] = []
    for path in paths:
        score = await score_product_image_async(path, category)
        scores.append({"path": path, "score": score})

    # 정면 패키지 베스트
    best_pkg = None
    best_pkg_v = -1.0
    for entry in scores:
        s = entry["score"]
        if not s.get("ok"):
            continue
        v = s.get("is_package_front", 0.0) - 0.5 * s.get("has_clutter", 0.0)
        if v > best_pkg_v:
            best_pkg_v = v
            best_pkg = entry["path"]

    # 내용물 베스트 (해당 카테고리만)
    best_content = None
    if _wants_content(category):
        best_content_v = -1.0
        for entry in scores:
            s = entry["score"]
            if not s.get("ok"):
                continue
            v = s.get("is_content_visible", 0.0) - 0.3 * s.get("has_text_overlay", 0.0)
            if v > best_content_v and v > 0.3:  # 최소 임계값
                best_content_v = v
                best_content = entry["path"]
        # 정면과 같은 사진이면 다음 후보로
        if best_content == best_pkg:
            best_content = None
            for entry in scores:
                if entry["path"] == best_pkg:
                    continue
                s = entry["score"]
                if not s.get("ok"):
                    continue
                if s.get("is_content_visible", 0.0) > 0.3:
                    best_content = entry["path"]
                    break

    return {
        "best_package": best_pkg,
        "best_content": best_content,
        "all_scores": scores,
    }


async def verify_set_count_async(
    image_path: str,
    expected_count: int,
) -> dict:
    """이미지에서 패키지 개수 추출 후 expected_count 와 비교.

    반환:
        {
            "expected": int,
            "detected_count": int,
            "confidence": float,
            "matches": bool,
            "suggestion": "정확" | "수정 권장: N개로 보임" | "확신 부족",
            "ok": bool,
        }
    """
    result = await count_packages_in_image_async(image_path)
    if not result.get("ok"):
        return {
            "expected": expected_count,
            "detected_count": 0,
            "confidence": 0.0,
            "matches": False,
            "suggestion": result.get("note") or "이미지 분석 실패",
            "ok": False,
        }

    detected = int(result.get("count", 0))
    confidence = float(result.get("confidence", 0.0))
    matches = detected == expected_count

    if matches:
        suggestion = "정확"
    elif confidence >= _VERIFY_CONF_HIGH:
        suggestion = f"수정 권장: {detected}개로 보임 (현재 {expected_count})"
    else:
        suggestion = "확신 부족 — 사람 확인 필요"

    return {
        "expected": expected_count,
        "detected_count": detected,
        "confidence": confidence,
        "matches": matches,
        "suggestion": suggestion,
        "ok": True,
    }


def select_best_images(image_paths: list[str], category: str = "기타") -> dict:
    """동기 래퍼 — CLI / 검증용."""
    return run_sync(select_best_images_async(image_paths, category))


def verify_set_count(image_path: str, expected_count: int) -> dict:
    """동기 래퍼 — CLI / 검증용."""
    return run_sync(verify_set_count_async(image_path, expected_count))


__all__ = [
    "select_best_images",
    "select_best_images_async",
    "verify_set_count",
    "verify_set_count_async",
]
