"""큐텐 등록용 콘텐츠 생성 (Phase 4-B + qoo10-seo-guide.md).

가이드:
    - title_jp — 일본어 상품명 (최대 100자, 첫 30자 핵심 노출)
    - tags — 검색 키워드 5~10개 (상품명 단어와 중복 X)
    - option_name — 단품/세트 표기
    - marketing_points — 홍보문구 3~4개 (이벤트 문구 여기에)

env: QOO10_CONTENT_MODEL=<provider:model>  (기본 추천 ollama:qwen3:14b — 일본어/한국어 전환 강함)
prompt: app/services/llm/prompts/qoo10_content.txt

사용:
    res = await generate_qoo10_content_async(
        product_name_kr="메디큐브 AGE-R 부스터 프로",
        category="03.뷰티&화장품",
        price_krw=180_000,
        option_name_kr="default",
    )
    # res = {"title_jp": "...", "tags": [...], "option_name": "...", "marketing_points": [...]}
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


def _empty() -> dict:
    return {
        "title_jp": "",
        "tags": [],
        "option_name": "",
        "marketing_points": [],
        "marketing_points_ko": [],   # H (5/3): 사장님 검수용 한글 번역 (parallel array)
        "ok": False,
    }


def _truncate_title(s: str, limit: int = 100) -> str:
    """큐텐 가이드 — 상품명 100자 (첫 30자 핵심)."""
    s = (s or "").strip()
    return s[:limit]


def _normalize_tags(tags) -> list[str]:
    if not isinstance(tags, list):
        return []
    out = []
    seen = set()
    for t in tags:
        if not isinstance(t, str):
            continue
        t = t.strip()
        if not t or len(t) > 12 or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= 10:
            break
    return out


def _normalize_marketing(points) -> list[str]:
    if not isinstance(points, list):
        return []
    out = []
    for p in points:
        if not isinstance(p, str):
            continue
        p = p.strip()
        if not p:
            continue
        out.append(p[:50])
        if len(out) >= 4:
            break
    return out


async def generate_qoo10_content_async(
    product_name_kr: str,
    category: str = "기타",
    price_krw: int | None = None,
    option_name_kr: str = "default",
    related_popular_keywords: list[dict] | None = None,
) -> dict:
    """한국 상품 → 큐텐 등록용 콘텐츠 (LLM 호출).

    related_popular_keywords (QQQ-1): [{"keyword_jp": str, "search_volume": int, ...}]
      → SEO 부스트용 인기 검색어. LLM 이 title_jp/tags 에 자연 포함.

    실패 시 ok=False, 빈 필드 반환 (자동화 막지 않음).
    """
    name = (product_name_kr or "").strip()
    if not name:
        return _empty()

    try:
        client = get_client_for("qoo10_content")
    except Exception as e:
        logger.error(f"[qoo10_content] 클라이언트 생성 실패 ({e})")
        return _empty()

    # 인기 검색어 블록 (없으면 빈 줄)
    if related_popular_keywords:
        related_block = "\n".join(
            f"- {r['keyword_jp']:30s} (검색량 {r.get('search_volume', 0):,})"
            for r in related_popular_keywords[:8]
        )
    else:
        related_block = "(제공된 관련 인기 검색어 없음)"

    template = load_prompt("qoo10_content")
    prompt = (
        template
        .replace("{product_name_kr}", name)
        .replace("{category}", category or "기타")
        .replace("{price_krw}", str(price_krw or "(미상)"))
        .replace("{option_name_kr}", option_name_kr or "default")
        .replace("{related_popular_keywords}", related_block)
    )

    try:
        # qwen3:14b 같은 reasoning 모델은 thinking 토큰 포함이라 num_predict 넉넉히
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            json_mode=True,
            max_tokens=2048,
        )
    except Exception as e:
        logger.error(f"[qoo10_content] LLM 호출 실패 ({e})")
        return _empty()

    text = (result.text or "").strip()
    if not text:
        logger.warning(f"[qoo10_content] 빈 응답")
        return _empty()

    s = _strip_codefence(text)
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        logger.warning(f"[qoo10_content] JSON 파싱 실패: {text[:120]!r}")
        return _empty()

    if not isinstance(parsed, dict):
        return _empty()

    title = _truncate_title(parsed.get("title_jp") or "", 100)
    tags = _normalize_tags(parsed.get("tags") or [])
    option_name = _truncate_title(parsed.get("option_name") or option_name_kr, 100)
    marketing = _normalize_marketing(parsed.get("marketing_points") or [])

    # H (5/3): 한글 번역 parallel array — marketing 길이에 맞춰 padding/truncate
    marketing_ko_raw = parsed.get("marketing_points_ko") or []
    marketing_ko: list[str] = []
    if isinstance(marketing_ko_raw, list):
        for k in marketing_ko_raw:
            if isinstance(k, str):
                marketing_ko.append(k.strip()[:60])
    # marketing 와 길이 일치 (부족하면 빈 문자열로 padding, 넘치면 자름)
    if len(marketing_ko) < len(marketing):
        marketing_ko += [""] * (len(marketing) - len(marketing_ko))
    elif len(marketing_ko) > len(marketing):
        marketing_ko = marketing_ko[: len(marketing)]

    ok = bool(title and tags and marketing)  # 핵심 3개 다 있으면 OK
    return {
        "title_jp": title,
        "tags": tags,
        "option_name": option_name,
        "marketing_points": marketing,
        "marketing_points_ko": marketing_ko,
        "ok": ok,
    }


def generate_qoo10_content(
    product_name_kr: str,
    category: str = "기타",
    price_krw: int | None = None,
    option_name_kr: str = "default",
) -> dict:
    """동기 래퍼."""
    return run_sync(
        generate_qoo10_content_async(product_name_kr, category, price_krw, option_name_kr)
    )


__all__ = ["generate_qoo10_content", "generate_qoo10_content_async"]
