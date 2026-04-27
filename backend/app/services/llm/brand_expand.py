"""브랜드 키워드 확장 (Phase 1-D, 명세 3.3#1~3).

is_brand=1 키워드 → 큐텐 상위 N개 상품명 → LLM 이 specific 키워드 3~5개 추출.

env: BRAND_EXPAND_MODEL=<provider:model>  (기본 추천 ollama:qwen3:14b)
prompt: app/services/llm/prompts/brand_expansion.txt

사용:
    res = await expand_brand_keyword_async(
        brand_jp="アヌア",
        brand_kr="아누아",
        product_names=["アヌア 어성초 토너 250ml", "アヌア PDRN 세럼 ...", ...],
    )
    # res = [{"keyword_jp": "anua pdrn", "keyword_kr": "아누아 PDRN"}, ...]
"""
from __future__ import annotations

import json
import logging
import re

from ._sync import run_sync
from .router import get_client_for, load_prompt

logger = logging.getLogger(__name__)


def _strip_codefence(s: str) -> str:
    s = re.sub(r"^```(?:json)?\s*", "", s.strip())
    s = re.sub(r"\s*```\s*$", "", s)
    return s


def _normalize_expansions(parsed) -> list[dict]:
    """LLM 응답 → [{keyword_jp, keyword_kr}, ...] 정규화.

    - 빈 keyword_jp 제거
    - 길이 검증 (1~80자)
    - 중복 제거 (keyword_jp lowercase 기준)
    """
    if not isinstance(parsed, dict):
        return []
    raw = parsed.get("expansions") or parsed.get("keywords") or []
    if not isinstance(raw, list):
        return []
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        jp = (item.get("keyword_jp") or "").strip()
        kr = (item.get("keyword_kr") or "").strip()
        if not jp or len(jp) > 80:
            continue
        key = jp.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"keyword_jp": jp[:80], "keyword_kr": kr[:80]})
        if len(out) >= 5:
            break
    return out


async def expand_brand_keyword_async(
    brand_jp: str,
    brand_kr: str = "",
    product_names: list[str] | None = None,
) -> list[dict]:
    """브랜드 키워드 → specific 키워드 확장.

    실패 시 빈 리스트 반환 (자동화 막지 않음).
    product_names 가 비면 빈 리스트.
    """
    name = (brand_jp or "").strip()
    if not name or not product_names:
        return []

    products = [p.strip() for p in product_names if p and p.strip()][:10]
    if not products:
        return []

    try:
        client = get_client_for("brand_expand")
    except Exception as e:
        logger.error(f"[brand_expand] 클라이언트 생성 실패 ({e})")
        return []

    template = load_prompt("brand_expansion")
    products_block = "\n".join(f"- {p[:100]}" for p in products)
    prompt = (
        template
        .replace("{brand_jp}", name)
        .replace("{brand_kr}", brand_kr or "(미상)")
        .replace("{products_block}", products_block)
    )

    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            json_mode=True,
            max_tokens=2048,
        )
    except Exception as e:
        logger.error(f"[brand_expand] LLM 호출 실패 ({e})")
        return []

    text = (result.text or "").strip()
    if not text:
        logger.warning(f"[brand_expand] 빈 응답")
        return []

    s = _strip_codefence(text)
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        logger.warning(f"[brand_expand] JSON 파싱 실패: {text[:120]!r}")
        return []

    return _normalize_expansions(parsed)


def expand_brand_keyword(
    brand_jp: str,
    brand_kr: str = "",
    product_names: list[str] | None = None,
) -> list[dict]:
    """동기 래퍼."""
    return run_sync(expand_brand_keyword_async(brand_jp, brand_kr, product_names))


__all__ = ["expand_brand_keyword", "expand_brand_keyword_async"]
