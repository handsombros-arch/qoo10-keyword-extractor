"""매칭 품질 자동 평가 (III-1).

각 (큐텐, 한국) 매칭 직후 quality_score 계산 — image_score, text_score,
cover_description 자카드를 결합. 낮으면 decision='needs_review' 라벨링.

설정 우선순위 (UserData > env > 기본값):
    UserData key='quality_thresholds':
        {"accept": 0.7, "review": 0.5, "desc_weight": 0.25,
         "image_weight_with_desc": 0.6, "image_weight_no_desc": 0.75}
    env:  QUALITY_ACCEPT_THRESHOLD / QUALITY_REVIEW_THRESHOLD / QUALITY_DESC_WEIGHT
    기본: 0.70 / 0.50 / 0.25

decision 룰:
    quality_score >= accept   AND ok → accepted
    quality_score >= review   AND ok → needs_review (사장님 검수 우선)
    그 외                            → rejected

UserData 변경 시 invalidate_quality_cache() 호출하면 다음 호출에 반영.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9가-힣ぁ-ヿ一-龥]+")

# UserData 캐시 — 30초 TTL (매칭 루프 중 빈번 호출 방지)
_CACHE: dict = {"data": None, "expires_at": 0.0}
_CACHE_TTL = 30.0


def _env_float(key: str, default: float) -> float:
    try:
        v = os.getenv(key)
        return float(v) if v not in (None, "") else default
    except Exception:
        return default


def invalidate_quality_cache() -> None:
    """UserData 저장 직후 호출 — 다음 매칭에 새 값 반영."""
    _CACHE["data"] = None
    _CACHE["expires_at"] = 0.0


def _build_thresholds(user: dict) -> dict:
    return {
        "accept": float(user.get("accept",
            _env_float("QUALITY_ACCEPT_THRESHOLD", 0.70))),
        "review": float(user.get("review",
            _env_float("QUALITY_REVIEW_THRESHOLD", 0.50))),
        "desc_weight": float(user.get("desc_weight",
            _env_float("QUALITY_DESC_WEIGHT", 0.25))),
        "image_weight_with_desc": float(user.get("image_weight_with_desc", 0.60)),
        "image_weight_no_desc": float(user.get("image_weight_no_desc", 0.75)),
    }


async def warm_quality_cache() -> dict:
    """UserData key='quality_thresholds' async 조회 + 캐시 갱신.

    매칭 endpoint 진입 시 한 번 호출. compute_quality_score 가 sync 라 async 우회 필요.
    """
    user = {}
    try:
        from app.db.connection import async_session
        from app.db.models import UserData
        from sqlalchemy import select
        async with async_session() as s:
            r = await s.execute(
                select(UserData.data).where(UserData.key == "quality_thresholds").limit(1)
            )
            row = r.first()
            if row and row[0]:
                user = json.loads(row[0])
    except Exception as e:
        logger.debug(f"[match_quality] UserData async load fail: {e}")

    out = _build_thresholds(user)
    _CACHE["data"] = out
    _CACHE["expires_at"] = time.time() + _CACHE_TTL
    return out


def _get_thresholds() -> dict:
    """캐시 → env → default. async warm 안 됐으면 env 값으로."""
    if _CACHE["data"] is not None and time.time() < _CACHE["expires_at"]:
        return _CACHE["data"]
    out = _build_thresholds({})
    _CACHE["data"] = out
    _CACHE["expires_at"] = time.time() + _CACHE_TTL
    return out


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return set(t.lower() for t in _TOKEN_RE.findall(text) if len(t) >= 2)


def description_jaccard(desc_a: str, desc_b: str) -> float:
    """두 cover description (영문 위주) 자카드 유사도."""
    a, b = _tokens(desc_a), _tokens(desc_b)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def compute_quality_score(
    image_score: float,
    text_score: float,
    desc_a: str | None = None,
    desc_b: str | None = None,
) -> tuple[float, float]:
    """결합 quality 계산 — 이미지 우세 (jp/ko 자카드 본질적 낮음 보정).

    가중치는 UserData (quality_thresholds) > env > 기본 순.

    returns: (quality_score, description_jaccard)
    """
    img = max(0.0, min(1.0, float(image_score or 0.0)))
    txt = max(0.0, min(1.0, float(text_score or 0.0)))

    th = _get_thresholds()
    has_desc = bool(desc_a and desc_b)
    if has_desc:
        d = description_jaccard(desc_a or "", desc_b or "")
        desc_w = th["desc_weight"]
        img_w = th["image_weight_with_desc"]
        txt_w = max(0.05, 1.0 - img_w - desc_w)
        q = img_w * img + txt_w * txt + desc_w * d
    else:
        d = 0.0
        img_w = th["image_weight_no_desc"]
        txt_w = max(0.05, 1.0 - img_w)
        q = img_w * img + txt_w * txt
    return max(0.0, min(1.0, q)), d


def decide_with_quality(
    quality_score: float,
    image_ok: bool,
) -> str:
    """quality_score → decision 라벨 (UserData 임계값 우선)."""
    if not image_ok:
        return "rejected"
    th = _get_thresholds()
    if quality_score >= th["accept"]:
        return "accepted"
    if quality_score >= th["review"]:
        return "needs_review"
    return "rejected"


__all__ = [
    "compute_quality_score",
    "decide_with_quality",
    "description_jaccard",
    "invalidate_quality_cache",
    "warm_quality_cache",
]
