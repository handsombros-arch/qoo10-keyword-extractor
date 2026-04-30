"""SEO 콘텐츠 보강 — 관련 인기 검색어 추출 (QQQ-1).

용도:
  qoo10_content 생성 시 LLM 에 "이 상품과 관련된 큐텐 인기 검색어 N개" 를 함께 전달.
  LLM 이 title_jp + tags 에 자연스럽게 포함하여 큐텐 검색 노출 ↑.

매칭 우선순위 (가장 적합한 것 먼저):
  1) 같은 brand (브랜드 키워드끼리)
  2) 같은 category_inferred (LLM 분류)
  3) 키워드 substring 매치 (예: "메디큐브 부스터" → "메디큐브 AGE-R" 도 관련)
  4) 자기 자신 제외

정렬: search_volume_weekly DESC.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select, or_, func, desc

logger = logging.getLogger(__name__)

# 일본어 토큰화 — 공백/구두점 분리, 카타카나/한자/영문 단어 추출
_TOKEN_RE = re.compile(r"[a-zA-Z0-9가-힣ぁ-ヿ一-龥]+")


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return set(t.lower() for t in _TOKEN_RE.findall(text) if len(t) >= 2)


async def get_related_popular_keywords_async(
    keyword_jp: str,
    category: str | None = None,
    brand_jp: str | None = None,
    limit: int = 8,
    min_search_volume: int = 0,
) -> list[dict]:
    """이 키워드와 관련된 인기 검색어 N개.

    returns: [{"keyword_jp": str, "keyword_kr": str, "search_volume": int, "match_kind": str}, ...]
    """
    from app.db.connection import async_session
    from app.db.models import Keyword

    if not keyword_jp:
        return []

    target_tokens = _tokens(keyword_jp)

    candidates: dict[str, dict] = {}  # keyword_jp → meta (dedup)

    async with async_session() as s:
        # 1) 같은 브랜드 우선 (있는 경우만)
        if brand_jp:
            r = await s.execute(
                select(Keyword.keyword_jp, Keyword.keyword_kr,
                       Keyword.search_volume_weekly, Keyword.brand_jp)
                .where(Keyword.brand_jp == brand_jp)
                .where(Keyword.keyword_jp != keyword_jp)
                .where(Keyword.search_volume_weekly >= min_search_volume)
                .order_by(desc(Keyword.search_volume_weekly))
                .limit(limit * 2)
            )
            for kw, kr, sv, bj in r.all():
                if kw not in candidates:
                    candidates[kw] = {
                        "keyword_jp": kw, "keyword_kr": kr or "",
                        "search_volume": sv or 0, "match_kind": "brand",
                    }

        # 2) 같은 카테고리 (브랜드 매치 부족 시)
        if category and len(candidates) < limit * 2:
            r = await s.execute(
                select(Keyword.keyword_jp, Keyword.keyword_kr,
                       Keyword.search_volume_weekly)
                .where(Keyword.category_inferred == category)
                .where(Keyword.keyword_jp != keyword_jp)
                .where(Keyword.search_volume_weekly >= min_search_volume)
                .order_by(desc(Keyword.search_volume_weekly))
                .limit(limit * 3)
            )
            for kw, kr, sv in r.all():
                if kw not in candidates:
                    candidates[kw] = {
                        "keyword_jp": kw, "keyword_kr": kr or "",
                        "search_volume": sv or 0, "match_kind": "category",
                    }

        # 3) 토큰 substring 매치 (브랜드/카테고리 부족하거나 0 일 때 폴백)
        if len(candidates) < limit and target_tokens:
            # 같은 토큰 1개라도 포함하는 keyword
            token_filters = [
                Keyword.keyword_jp.ilike(f"%{t}%") for t in list(target_tokens)[:5]
            ]
            r = await s.execute(
                select(Keyword.keyword_jp, Keyword.keyword_kr,
                       Keyword.search_volume_weekly)
                .where(or_(*token_filters))
                .where(Keyword.keyword_jp != keyword_jp)
                .where(Keyword.search_volume_weekly >= min_search_volume)
                .order_by(desc(Keyword.search_volume_weekly))
                .limit(limit * 3)
            )
            for kw, kr, sv in r.all():
                if kw not in candidates:
                    candidates[kw] = {
                        "keyword_jp": kw, "keyword_kr": kr or "",
                        "search_volume": sv or 0, "match_kind": "token",
                    }

    # 정렬 — match_kind 우선순위 + search_volume 내림차순
    kind_rank = {"brand": 0, "category": 1, "token": 2}
    sorted_items = sorted(
        candidates.values(),
        key=lambda x: (kind_rank.get(x["match_kind"], 9), -x["search_volume"]),
    )
    return sorted_items[:limit]


__all__ = ["get_related_popular_keywords_async"]
