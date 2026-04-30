"""자동 학습 루프 (KKK-1).

사장님 corrections 누적 → 다음 야간 자동화에 자동 반영.

A. reject blocklist     — load_reject_blocklist(): set of (qoo10_id, domestic_id)
                          매칭 직전 in-memory check. INSERT 안 함, decision='rejected' INSERT.

B. preferred kw 주입    — inject_user_preferred_keywords(target_date):
                          최근 N일 swap 사례 → expanded_keywords 에 source_count=-1 (sentinel)
                          으로 INSERT. 다음 야간 expanded_search 가 자동 사용.

C. quality auto-tune    — autotune_quality_thresholds():
                          최근 N일 swap_rate 측정 → UserData(quality_thresholds) 자동 ±0.05.
                          매주 1회 권장 (daily_workflow STEP 7 또는 cron).

env:
    AUTO_LEARNING_LOOKBACK_DAYS         (기본 14)
    AUTO_LEARNING_PREFERRED_MIN_COUNT   (기본 1 — 1번 swap 만으로도 학습)
    AUTO_LEARNING_TUNE_HIGH_SWAP        (기본 0.30 — 30%+ swap 시 임계값 ↑)
    AUTO_LEARNING_TUNE_LOW_SWAP         (기본 0.05 — 5%- swap 시 임계값 ↓)
    AUTO_LEARNING_TUNE_DELTA            (기본 0.05)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import select, func

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    try:
        v = os.getenv(key)
        return float(v) if v not in (None, "") else default
    except Exception:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        v = os.getenv(key)
        return int(v) if v not in (None, "") else default
    except Exception:
        return default


# ─── A. reject blocklist ─────────────────────────────────


async def load_reject_blocklist() -> set[tuple[int, int]]:
    """user_corrections 의 reject 사례 (qid, did) 쌍 집합.

    매칭 endpoint 진입 시 한 번 호출 → 매칭 루프에서 in-memory check.
    """
    from app.db.connection import async_session
    from app.db.models import UserCorrection

    pairs: set[tuple[int, int]] = set()
    try:
        async with async_session() as s:
            r = await s.execute(
                select(UserCorrection.ai_choice_id, UserCorrection.user_choice_id)
                .where(UserCorrection.decision_kind == "reject")
            )
            for ai_id, user_id in r.all():
                # reject 면 ai_choice_id 가 잘못된 매칭 (사장님이 거부)
                # user_choice_id 는 None (대안 없이 거부)
                if ai_id:
                    # qid 모름 — 한국 SKU id 만. (qid, did) 쌍 구성을 위해 추가 정보 필요.
                    # 단순화: ai_choice_id (한국 SKU id) 자체를 blocklist 키로 사용
                    pairs.add((-1, ai_id))  # qid=-1 = wildcard
    except Exception as e:
        logger.debug(f"[auto_learning] blocklist load fail: {e}")
    return pairs


def is_blocked(blocklist: set, qid: int, did: int) -> bool:
    """매칭 전 check — wildcard (-1, did) 또는 정확 (qid, did) 매치."""
    return ((qid, did) in blocklist) or ((-1, did) in blocklist)


# ─── B. preferred keyword 자동 주입 ────────────────────


async def inject_user_preferred_keywords(target_date) -> dict:
    """swap 사례에서 사장님이 선택한 SKU 의 search_keyword → expanded_keywords INSERT.

    이후 expanded_search (STEP 5.8) 가 자동으로 그 키워드로 한국 검색 → 매칭 후보 풀 확장.

    returns: {processed: int, inserted: int, skipped_dup: int, items: [...]}
    """
    from app.db.connection import async_session
    from app.db.models import UserCorrection, DomesticProduct, ExpandedKeyword

    lookback_days = _env_int("AUTO_LEARNING_LOOKBACK_DAYS", 14)
    min_count = _env_int("AUTO_LEARNING_PREFERRED_MIN_COUNT", 1)
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    async with async_session() as s:
        # swap 사례 — keyword_jp + user_choice_id 필수
        r = await s.execute(
            select(
                UserCorrection.keyword_jp,
                UserCorrection.user_choice_id,
                func.count(UserCorrection.id).label("cnt"),
            )
            .where(UserCorrection.decision_kind == "swap")
            .where(UserCorrection.keyword_jp.is_not(None))
            .where(UserCorrection.user_choice_id.is_not(None))
            .where(UserCorrection.corrected_at >= cutoff)
            .group_by(UserCorrection.keyword_jp, UserCorrection.user_choice_id)
        )
        rows = r.all()

    if not rows:
        return {"processed": 0, "inserted": 0, "items": [],
                "message": f"최근 {lookback_days}일 swap 0건 — 학습할 데이터 없음"}

    inserted = 0
    skipped = 0
    items = []
    async with async_session() as s:
        for kw_jp, user_did, cnt in rows:
            if cnt < min_count:
                continue
            # user_choice_id → DomesticProduct.search_keyword
            d_row = (await s.execute(
                select(DomesticProduct.search_keyword)
                .where(DomesticProduct.id == user_did).limit(1)
            )).first()
            if not d_row or not d_row[0]:
                continue
            preferred_kr = d_row[0].strip()
            if not preferred_kr:
                continue

            # 이미 expanded_keywords 에 있으면 skip
            existing = (await s.execute(
                select(ExpandedKeyword.id)
                .where(ExpandedKeyword.parent_jp == kw_jp)
                .where(ExpandedKeyword.keyword_kr == preferred_kr)
                .limit(1)
            )).first()
            if existing:
                skipped += 1
                continue

            s.add(ExpandedKeyword(
                parent_jp=kw_jp,
                parent_kr=preferred_kr,
                keyword_jp=kw_jp,           # 일본어는 원본 그대로
                keyword_kr=preferred_kr,    # 사장님 학습 한국어
                source_count=-1,            # sentinel: -1 = user_correction (auto-learned)
            ))
            inserted += 1
            items.append({
                "keyword_jp": kw_jp,
                "preferred_kr": preferred_kr,
                "swap_count": cnt,
            })
        if inserted:
            await s.commit()

    return {
        "processed": len(rows),
        "inserted": inserted,
        "skipped_dup": skipped,
        "items": items,
        "lookback_days": lookback_days,
    }


# ─── C. quality 임계값 auto-tune ────────────────────


async def autotune_quality_thresholds() -> dict:
    """최근 N일 swap_rate 측정 → quality_thresholds 자동 조정.

    swap_rate = swap / (swap + accept_as_is)
    - high swap (>= 0.30): 매칭 너무 느슨 → accept +delta
    - low swap (< 0.05):   매칭 너무 빡빡 → accept -delta
    - 그 외: 변경 X

    returns: {decision, before, after, swap_rate, sample_size}
    """
    from app.db.connection import async_session
    from app.db.models import UserCorrection, UserData

    lookback_days = _env_int("AUTO_LEARNING_LOOKBACK_DAYS", 14)
    high = _env_float("AUTO_LEARNING_TUNE_HIGH_SWAP", 0.30)
    low = _env_float("AUTO_LEARNING_TUNE_LOW_SWAP", 0.05)
    delta = _env_float("AUTO_LEARNING_TUNE_DELTA", 0.05)
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    async with async_session() as s:
        r = await s.execute(
            select(UserCorrection.decision_kind, func.count())
            .where(UserCorrection.corrected_at >= cutoff)
            .where(UserCorrection.decision_kind.in_(("swap", "accept_as_is")))
            .group_by(UserCorrection.decision_kind)
        )
        counts = {k: c for k, c in r.all()}

    swap_n = counts.get("swap", 0)
    accept_n = counts.get("accept_as_is", 0)
    sample = swap_n + accept_n
    if sample < 5:
        return {"decision": "skip_insufficient", "sample_size": sample,
                "message": f"표본 {sample}건 — 최소 5건 필요"}

    swap_rate = swap_n / sample

    # 현재 임계값
    async with async_session() as s:
        existing = (await s.execute(
            select(UserData).where(UserData.key == "quality_thresholds")
        )).scalar_one_or_none()
        current = json.loads(existing.data) if existing and existing.data else {}

    current.setdefault("accept", 0.70)
    current.setdefault("review", 0.50)
    current.setdefault("desc_weight", 0.25)
    current.setdefault("image_weight_with_desc", 0.60)
    current.setdefault("image_weight_no_desc", 0.75)

    before_accept = current["accept"]
    new_accept = before_accept
    decision = "no_change"

    if swap_rate >= high:
        new_accept = min(0.95, before_accept + delta)
        decision = "tightened"
    elif swap_rate < low:
        new_accept = max(0.50, before_accept - delta)
        decision = "loosened"

    if new_accept == before_accept:
        return {
            "decision": decision,
            "swap_rate": round(swap_rate, 3),
            "sample_size": sample,
            "before": before_accept,
            "after": before_accept,
            "message": "임계값 변경 없음",
        }

    current["accept"] = round(new_accept, 2)
    current["review"] = round(max(0.30, new_accept - 0.20), 2)  # accept-0.20 으로 review 같이 이동

    blob = json.dumps(current, ensure_ascii=False)
    async with async_session() as s:
        existing = (await s.execute(
            select(UserData).where(UserData.key == "quality_thresholds")
        )).scalar_one_or_none()
        if existing:
            existing.data = blob
            existing.updated_at = datetime.utcnow()
        else:
            s.add(UserData(key="quality_thresholds", data=blob,
                           updated_at=datetime.utcnow()))
        await s.commit()

    # 캐시 무효화
    try:
        from app.services.match_quality import invalidate_quality_cache
        invalidate_quality_cache()
    except Exception:
        pass

    return {
        "decision": decision,
        "swap_rate": round(swap_rate, 3),
        "sample_size": sample,
        "before": before_accept,
        "after": current["accept"],
        "review_after": current["review"],
    }


__all__ = [
    "load_reject_blocklist",
    "is_blocked",
    "inject_user_preferred_keywords",
    "autotune_quality_thresholds",
]
