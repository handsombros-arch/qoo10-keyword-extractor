"""일본어 ↔ 한국어 텍스트 번역 (LLM + DB 캐시).

용도:
    - 큐텐 상품명(일본어) → 한국어 검색 키워드 변환 (3-1 매칭용)
    - 향후 다른 jp 텍스트 (옵션명/태그 등) 재사용

캐시:
    TranslationCache 테이블 PK = (source_text, source_lang, target_lang).
    같은 원문은 1회만 LLM 호출하고 다음부터 DB hit.

env: TRANSLATE_MODEL=<provider:model>  (기본 추천 ollama:qwen2.5:7b)
prompt: app/services/llm/prompts/jp_ko_translation.txt

사용:
    ko = await translate_jp_to_ko_async("メディキューブ ゼロ毛穴パッド 70枚")
    # → "메디큐브 제로 모공패드 70매"
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.connection import async_session
from app.db.models import TranslationCache

from ._sync import run_sync
from .router import get_client_for, load_prompt

logger = logging.getLogger(__name__)


def _strip_codefence(s: str) -> str:
    s = re.sub(r"^```(?:json)?\s*", "", s.strip())
    s = re.sub(r"\s*```\s*$", "", s)
    return s


def _parse_translation(raw: str) -> str | None:
    """LLM 응답에서 'ko' 필드 추출.

    JSON 파싱 실패 / 'ko' 필드 누락 시 None 반환 (DB UPDATE 스킵).
    이전 버전은 raw 첫 줄을 폴백 사용했으나 '{"ko": "...' 같은 JSON 잔재가
    그대로 ko 컬럼에 박히는 결함이 있어 제거.
    """
    if not raw:
        return None
    s = _strip_codefence(raw)
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    ko = (parsed.get("ko") or "").strip()
    return ko or None


async def _cache_get(source_text: str, src: str, tgt: str) -> str | None:
    try:
        async with async_session() as session:
            row = (await session.execute(
                select(TranslationCache).where(
                    TranslationCache.source_text == source_text,
                    TranslationCache.source_lang == src,
                    TranslationCache.target_lang == tgt,
                )
            )).scalar_one_or_none()
            if row and row.translated:
                return row.translated
    except Exception as e:
        logger.debug(f"[translate] 캐시 조회 실패: {e}")
    return None


async def _cache_put(source_text: str, src: str, tgt: str, translated: str, model: str) -> None:
    try:
        async with async_session() as session:
            session.add(TranslationCache(
                source_text=source_text,
                source_lang=src,
                target_lang=tgt,
                translated=translated,
                model=model,
            ))
            await session.commit()
    except IntegrityError:
        # 동시성으로 다른 워커가 먼저 INSERT — 정상
        pass
    except Exception as e:
        logger.warning(f"[translate] 캐시 저장 실패: {e}")


async def translate_jp_to_ko_async(product_name: str) -> str | None:
    """일본어 상품명 → 한국어 번역. 캐시 hit 면 LLM 호출 없음.

    빈/None 입력은 None 반환. 호출 실패 시 None 반환 (caller 가 폴백 처리).
    """
    name = (product_name or "").strip()
    if not name:
        return None

    cached = await _cache_get(name, "ja", "ko")
    if cached:
        return cached

    try:
        client = get_client_for("translate")
    except Exception as e:
        logger.error(f"[translate] 클라이언트 생성 실패 ({e})")
        return None

    template = load_prompt("jp_ko_translation")
    prompt = template.replace("{product_name}", name)

    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True,
            max_tokens=512,
        )
    except Exception as e:
        logger.error(f"[translate] LLM 호출 실패 ({e})")
        return None

    text = (result.text or "").strip()
    if len(text) < 1:
        logger.warning(
            f"[translate] 빈 응답 "
            f"(in_tok={result.input_tokens}, out_tok={result.output_tokens})"
        )
        return None

    ko = _parse_translation(text)
    if not ko:
        logger.warning(f"[translate] 파싱 실패: {text[:100]!r}")
        return None

    await _cache_put(name, "ja", "ko", ko, result.model)
    return ko


def translate_jp_to_ko(product_name: str) -> str | None:
    """동기 래퍼 — CLI / 테스트용."""
    return run_sync(translate_jp_to_ko_async(product_name))


__all__ = ["translate_jp_to_ko", "translate_jp_to_ko_async"]
