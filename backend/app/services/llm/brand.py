"""K-뷰티/K-식품 브랜드명 판별 (의역 방지).

흐름:
    1) Supabase brands 테이블 1차 매칭 (LLM 호출 0)
       - 토큰 단위 정확 매칭 (kr/jp/en 모든 별칭)
       - 토큰 미매칭 시, 띄어쓰기 없는 키워드 대응으로 부분 포함 매칭
         (별칭 길이 ≥ 2 글자, 가장 긴 별칭 우선)
    2) 미매칭 시 LLM (prompts/brand_detection.txt) 호출
    3) 응답 confidence > BRAND_AUTO_ADD_THRESHOLD (기본 0.9) 면
       brands 테이블에 INSERT (source="auto"). UNIQUE kr 충돌 시 무시.

반환 dict:
    {
      "is_brand": bool,
      "brand_kr": str, "brand_jp": str, "brand_en": str,
      "product_part": str,         # 키워드에서 브랜드를 뺀 나머지
      "confidence": float,
      "source": "whitelist" | "llm",
      "auto_added": bool,          # 이번 호출에서 brands 테이블에 신규 추가됐는지
    }

env: BRAND_MODEL=<provider:model>, BRAND_AUTO_ADD_THRESHOLD=0.9 (선택)
"""
from __future__ import annotations

import json
import logging
import os
import re

import json as jsonlib

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.connection import async_session
from app.db.models import Brand, UserData

from ._sync import run_sync
from .router import get_client_for, load_prompt

logger = logging.getLogger(__name__)

_TOKEN_SPLIT = re.compile(r"[\s\-_/,/&·\.\(\)\[\]\+]+")
_DEFAULT_THRESHOLD = 0.9
_THRESHOLD_KEY = "brand_auto_add_threshold"  # UserData 키 (프론트에서 조정)


def _env_threshold() -> float:
    try:
        return float(os.getenv("BRAND_AUTO_ADD_THRESHOLD", str(_DEFAULT_THRESHOLD)))
    except ValueError:
        return _DEFAULT_THRESHOLD


async def _threshold_async() -> float:
    """임계값 조회. DB(UserData) 1차 → env 2차 → 0.9 폴백.

    프론트가 /api/user-data/brand_auto_add_threshold 로 PUT 한 값이 우선.
    DB 조회 실패해도 자동화 막지 않도록 try/except.
    """
    try:
        async with async_session() as session:
            row = (await session.execute(
                select(UserData).where(UserData.key == _THRESHOLD_KEY)
            )).scalar_one_or_none()
            if row and row.data:
                payload = jsonlib.loads(row.data)
                if isinstance(payload, dict) and "value" in payload:
                    v = float(payload["value"])
                    if 0.0 <= v <= 1.0:
                        return v
                elif isinstance(payload, (int, float)):
                    v = float(payload)
                    if 0.0 <= v <= 1.0:
                        return v
    except Exception as e:
        logger.debug(f"[brand] DB 임계값 조회 실패 (env 로 폴백): {e}")
    return _env_threshold()


def _norm(s: str) -> str:
    """소문자 + 공백 제거. 별칭 매칭용."""
    return (s or "").strip().lower().replace(" ", "")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(text or "") if t]


def _all_aliases(b) -> list[str]:
    """Brand 의 모든 표기 (kr/jp/en + aliases JSON 배열)."""
    out = [b.kr or "", b.jp or "", b.en or ""]
    raw = getattr(b, "aliases", None)
    if raw and raw.strip() and raw.strip() != "[]":
        try:
            extra = json.loads(raw)
            if isinstance(extra, list):
                out.extend(str(x) for x in extra if x)
        except (json.JSONDecodeError, TypeError):
            pass
    return [a for a in out if a]


def _empty_result() -> dict:
    return {
        "is_brand": False,
        "brand_kr": "",
        "brand_jp": "",
        "brand_en": "",
        "product_part": "",
        "confidence": 0.0,
        "source": "llm",
        "auto_added": False,
    }


async def _all_brands() -> list[Brand]:
    async with async_session() as session:
        rows = (await session.execute(select(Brand))).scalars().all()
        return list(rows)


def _match_in_whitelist(keyword: str, brands: list[Brand]) -> Brand | None:
    """토큰 정확 매칭 → 부분 포함 (긴 별칭 우선) 매칭. 없으면 None."""
    if not keyword or not brands:
        return None

    norm_kw = _norm(keyword)
    tokens_norm = {_norm(t) for t in _tokens(keyword) if t}

    # 1) 토큰 정확 매칭 (kr/jp/en + aliases)
    for b in brands:
        for alias in _all_aliases(b):
            a = _norm(alias)
            if a and a in tokens_norm:
                return b

    # 2) 부분 포함 (별칭 길이 ≥ 2, 가장 긴 매칭 우선)
    candidates: list[tuple[int, Brand]] = []
    for b in brands:
        for alias in _all_aliases(b):
            a = _norm(alias)
            if a and len(a) >= 2 and a in norm_kw:
                candidates.append((len(a), b))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    return None


def _product_part_from_match(keyword: str, brand: Brand) -> str:
    """매칭된 브랜드 별칭(kr/jp/en + aliases)을 keyword 에서 제거한 나머지."""
    out = keyword
    for alias in _all_aliases(brand):
        out = re.sub(re.escape(alias), " ", out, flags=re.IGNORECASE)
    return _TOKEN_SPLIT.sub(" ", out).strip()


async def _try_insert(kr: str, jp: str, en: str, confidence: float) -> bool:
    """brands 에 INSERT. UNIQUE kr 충돌 시 False (이미 존재)."""
    if not kr:
        return False
    try:
        async with async_session() as session:
            session.add(Brand(
                kr=kr.strip(),
                jp=(jp or "").strip(),
                en=(en or "").strip(),
                source="auto",
                confidence=float(confidence or 0.0),
            ))
            await session.commit()
            return True
    except IntegrityError:
        return False
    except Exception as e:
        logger.warning(f"[brand] 자동 추가 실패 (무시): {e}")
        return False


def _parse_llm_json(text: str) -> dict | None:
    """LLM 응답에서 JSON 객체 한 개 파싱. 실패 시 None.

    LLM이 ```json ... ``` 코드블록을 두르거나 앞뒤 설명을 붙이는 경우 대응.
    """
    if not text:
        return None
    s = text.strip()
    # 코드블록 제거
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    # 첫 { 부터 마지막 } 까지
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return None


async def is_brand_keyword_async(keyword: str) -> dict:
    keyword = (keyword or "").strip()
    if not keyword:
        return _empty_result()

    # 1) DB 조회 + 매칭
    try:
        brands = await _all_brands()
    except Exception as e:
        logger.error(f"[brand] DB 조회 실패 ({e}) — LLM 으로 폴백")
        brands = []

    matched = _match_in_whitelist(keyword, brands) if brands else None
    if matched:
        return {
            "is_brand": True,
            "brand_kr": matched.kr or "",
            "brand_jp": matched.jp or "",
            "brand_en": matched.en or "",
            "product_part": _product_part_from_match(keyword, matched),
            "confidence": float(matched.confidence or 1.0),
            "source": "whitelist",
            "auto_added": False,
        }

    # 2) LLM
    try:
        client = get_client_for("brand")
    except Exception as e:
        logger.error(f"[brand] LLM 클라이언트 생성 실패 ({e})")
        return _empty_result()

    template = load_prompt("brand_detection")
    prompt = template.replace("{keyword}", keyword)

    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True,
            max_tokens=2048,  # Gemini 2.5 thinking 토큰 + JSON 응답 (한국어/일본어 토큰 여유)
        )
    except Exception as e:
        logger.error(f"[brand] LLM 호출 실패 ({e})")
        return _empty_result()

    parsed = _parse_llm_json(result.text)
    if not parsed or not isinstance(parsed, dict):
        logger.warning(f"[brand] JSON 파싱 실패: {result.text[:120]!r}")
        return _empty_result()

    is_brand = bool(parsed.get("is_brand"))
    brand_kr = (parsed.get("brand_kr") or "").strip()
    brand_jp = (parsed.get("brand_jp") or "").strip()
    brand_en = (parsed.get("brand_en") or "").strip()
    product_part = (parsed.get("product_part") or "").strip()
    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    auto_added = False
    threshold = await _threshold_async()
    if is_brand and brand_kr and confidence >= threshold:
        auto_added = await _try_insert(brand_kr, brand_jp, brand_en, confidence)
        if auto_added:
            logger.info(
                f"[brand] 자동 추가: kr={brand_kr!r} conf={confidence:.2f} (>= {threshold:.2f})"
            )

    return {
        "is_brand": is_brand,
        "brand_kr": brand_kr,
        "brand_jp": brand_jp,
        "brand_en": brand_en,
        "product_part": product_part,
        "confidence": confidence,
        "source": "llm",
        "auto_added": auto_added,
    }


def is_brand_keyword(keyword: str) -> dict:
    """동기 래퍼 — CLI / 검증용. event loop 안에서는 async 버전 직접 사용."""
    return run_sync(is_brand_keyword_async(keyword))


__all__ = ["is_brand_keyword", "is_brand_keyword_async"]
