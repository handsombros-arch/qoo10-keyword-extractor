"""일본어 ↔ 한국어 텍스트 번역 (LLM + DB 캐시 + 폴백 체인).

용도:
    - 큐텐 상품명(일본어) → 한국어 검색 키워드 변환 (3-1 매칭용)
    - 향후 다른 jp 텍스트 (옵션명/태그 등) 재사용

캐시:
    TranslationCache 테이블 PK = (source_text, source_lang, target_lang).
    같은 원문은 1회만 LLM 호출하고 다음부터 DB hit.

env:
    TRANSLATE_MODEL=<provider:model>            (기본 모델)
    TRANSLATE_FALLBACK_MODELS=<spec1>,<spec2>   (선택, 콤마 구분 — 첫 모델 실패 시 순차 폴백)

prompt: app/services/llm/prompts/jp_ko_translation.txt

사용:
    ko = await translate_jp_to_ko_async("メディキューブ ゼロ毛穴パッド 70枚")
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.connection import async_session
from app.db.models import TranslationCache

from ._sync import run_sync
from .base import LLMClient
from .router import _build_client, get_client_for, load_prompt

logger = logging.getLogger(__name__)

_KANA_DICT_PATH = Path(__file__).resolve().parents[2] / "data" / "jp_kana_to_ko.json"


@lru_cache(maxsize=1)
def _load_kana_dict() -> list[tuple[str, str]]:
    """jp_kana_to_ko.json 매핑을 (jp, ko) 튜플 리스트로. 긴 매핑 우선 정렬."""
    if not _KANA_DICT_PATH.exists():
        return []
    try:
        data = json.loads(_KANA_DICT_PATH.read_text(encoding="utf-8"))
        m = data.get("mappings", {})
        return sorted(m.items(), key=lambda x: -len(x[0]))
    except Exception as e:
        logger.warning(f"[translate] 카나 사전 로드 실패: {e}")
        return []


def postprocess_ko(ko: str) -> str:
    """LLM 번역 결과에 카나 후처리 적용. 잔존 카타카나/히라가나 단어 substitution.

    긴 매핑 우선. 매칭이 없으면 원문 그대로 반환.
    """
    if not ko:
        return ko
    out = ko
    for jp, ko_repl in _load_kana_dict():
        if jp in out:
            out = out.replace(jp, ko_repl)
    return out


def _strip_codefence(s: str) -> str:
    s = re.sub(r"^```(?:json)?\s*", "", s.strip())
    s = re.sub(r"\s*```\s*$", "", s)
    return s


def _parse_translation(raw: str) -> str | None:
    """LLM 응답에서 'ko' 필드 추출. 파싱 실패 시 None."""
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
        pass
    except Exception as e:
        logger.warning(f"[translate] 캐시 저장 실패: {e}")


def _fallback_specs() -> list[str]:
    """env TRANSLATE_FALLBACK_MODELS 콤마 구분 → 모델 spec 리스트."""
    raw = (os.getenv("TRANSLATE_FALLBACK_MODELS") or "").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


async def _try_translate_with(client: LLMClient, prompt: str) -> tuple[str | None, str]:
    """단일 클라이언트로 번역 시도. (ko, model_name) 반환. 실패 시 ko=None."""
    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True,
            max_tokens=2048,
        )
    except Exception as e:
        logger.warning(f"[translate] {client.name} 호출 실패: {e}")
        return None, client.name

    text = (result.text or "").strip()
    if not text:
        logger.warning(
            f"[translate] {client.name} 빈 응답 "
            f"(in_tok={result.input_tokens}, out_tok={result.output_tokens})"
        )
        return None, result.model

    ko = _parse_translation(text)
    if not ko:
        logger.warning(f"[translate] {client.name} 파싱 실패: {text[:100]!r}")
        return None, result.model

    return ko, result.model


async def translate_jp_to_ko_async(product_name: str) -> str | None:
    """일본어 상품명 → 한국어 번역. 캐시 + 폴백 체인.

    흐름:
        1) translation_cache hit 시 즉시 반환
        2) TRANSLATE_MODEL 으로 1차 시도
        3) 빈 응답/파싱 실패 시 TRANSLATE_FALLBACK_MODELS 의 모델로 순차 재시도
        4) 모두 실패 시 None
    """
    name = (product_name or "").strip()
    if not name:
        return None

    cached = await _cache_get(name, "ja", "ko")
    if cached:
        return cached

    template = load_prompt("jp_ko_translation")
    prompt = template.replace("{product_name}", name)

    # 1차 — TRANSLATE_MODEL
    try:
        primary = get_client_for("translate")
    except Exception as e:
        logger.error(f"[translate] 1차 클라이언트 생성 실패 ({e})")
        primary = None

    if primary is not None:
        ko, used_model = await _try_translate_with(primary, prompt)
        if ko:
            ko = postprocess_ko(ko)
            await _cache_put(name, "ja", "ko", ko, used_model)
            return ko

    # 2차+ — 폴백 체인
    for spec in _fallback_specs():
        try:
            fb_client = _build_client(spec)
        except Exception as e:
            logger.warning(f"[translate] 폴백 {spec} 빌드 실패: {e}")
            continue
        ko, used_model = await _try_translate_with(fb_client, prompt)
        if ko:
            logger.info(f"[translate] 폴백 hit ({spec}) for {name[:30]!r}")
            ko = postprocess_ko(ko)
            await _cache_put(name, "ja", "ko", ko, used_model)
            return ko

    logger.warning(f"[translate] 모든 모델 실패: {name[:50]!r}")
    return None


def translate_jp_to_ko(product_name: str) -> str | None:
    """동기 래퍼 — CLI / 테스트용."""
    return run_sync(translate_jp_to_ko_async(product_name))


__all__ = ["translate_jp_to_ko", "translate_jp_to_ko_async", "postprocess_ko"]
