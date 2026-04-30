"""키워드 의역/대안 생성 (HHH-1).

매칭 정합도 낮은 keyword_kr 에 대해 LLM 으로 한국 쇼핑몰 검색에 더 적합한
대안 키워드 2~3개 생성. brand_expand 와 달리 브랜드 확장이 아니라
**같은 의미의 다른 표현** (의역) 이 목표.

env: KEYWORD_ALTS_MODEL (기본 fallback: BRAND_EXPAND_MODEL)
prompt: app/services/llm/prompts/keyword_alternatives.txt

사용:
    alts = await generate_keyword_alts_async(
        keyword_jp="ダルバ 下地",
        keyword_kr="달바 기초",
        product_names=["ダルバ ホワイトトリュフ ファンデーション ベース...", ...],
    )
    # → [{"keyword_kr": "달바 베이스 메이크업", "reason": "..."}, ...]
"""
from __future__ import annotations

import json
import logging
import os
import re

from .router import get_client_for, load_prompt

logger = logging.getLogger(__name__)

_KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")


def _strip_codefence(s: str) -> str:
    s = re.sub(r"^```(?:json)?\s*", "", s.strip())
    s = re.sub(r"\s*```\s*$", "", s)
    return s


def _normalize(parsed, original_kr: str) -> list[dict]:
    if not isinstance(parsed, dict):
        return []
    raw = parsed.get("alternatives") or []
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    orig = (original_kr or "").strip().lower()
    if orig:
        seen.add(orig)
    for item in raw:
        if not isinstance(item, dict):
            continue
        kr = (item.get("keyword_kr") or "").strip()
        reason = (item.get("reason") or "").strip()
        if not kr or len(kr) > 80:
            continue
        # 카나 잔존 폐기
        if _KANA_RE.search(kr):
            logger.warning(f"[keyword_alts] 카나 잔존 → 폐기: {kr!r}")
            continue
        key = kr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"keyword_kr": kr[:80], "reason": reason[:200]})
        if len(out) >= 3:
            break
    return out


async def generate_keyword_alts_async(
    keyword_jp: str,
    keyword_kr: str,
    product_names: list[str] | None = None,
) -> list[dict]:
    """원래 keyword_kr 에 대한 한국 검색 대안 키워드 생성.

    실패 시 빈 리스트.
    """
    if not keyword_kr:
        return []
    products = [p.strip() for p in (product_names or []) if p and p.strip()][:8]

    # KEYWORD_ALTS_MODEL 우선, 없으면 brand_expand 모델로 폴백
    domain = "keyword_alts" if os.getenv("KEYWORD_ALTS_MODEL") else "brand_expand"
    try:
        client = get_client_for(domain)
    except Exception as e:
        logger.error(f"[keyword_alts] 클라이언트 생성 실패 ({e})")
        return []

    template = load_prompt("keyword_alternatives")
    products_block = "\n".join(f"- {p[:100]}" for p in products) if products else "(상품명 없음)"
    prompt = (
        template
        .replace("{keyword_jp}", keyword_jp or "(미상)")
        .replace("{keyword_kr}", keyword_kr)
        .replace("{products_block}", products_block)
    )

    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            json_mode=True,
            max_tokens=1024,
        )
    except Exception as e:
        logger.error(f"[keyword_alts] LLM 호출 실패 ({e})")
        return []

    text = (result.text or "").strip()
    if not text:
        return []

    s = _strip_codefence(text)
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        logger.warning(f"[keyword_alts] JSON 파싱 실패: {text[:120]!r}")
        return []

    return _normalize(parsed, keyword_kr)


__all__ = ["generate_keyword_alts_async"]
