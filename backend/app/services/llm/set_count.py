"""큐텐 상품명 → 세트 묶음 개수 추출.

흐름:
    1) 정규식 1차 — 명백한 패턴 ("3개입", "5本", "× 5", "10매입", "1+1") 즉시 처리
    2) LLM 폴백 (prompts/set_count_extraction.txt). 응답에서 첫 정수 추출
    3) 1~99 범위 검증. 그 외 → 1 폴백

env: SET_COUNT_MODEL=<provider:model>

사용:
    n = await extract_set_count_async("아누아 토너 3개세트")  # → 3
    n = extract_set_count("AirPods")  # → 1 (sync 래퍼)
"""
from __future__ import annotations

import logging
import re

from ._sync import run_sync
from .router import get_client_for, load_prompt

logger = logging.getLogger(__name__)

_MIN, _MAX = 1, 99
_FALLBACK = 1

# 정규식 1차 — 명백한 N+단위 패턴.
# 단위 문자열은 한국어/일본어/영어 자주 나오는 묶음 단위만.
_UNIT_PATTERN = re.compile(
    r"(\d{1,2})\s*"
    r"(?:개입|개\s*세트|개\s*묶음|매입|매\s*세트|팩\s*세트|팩|봉|봉지|입|세트|"
    r"本|個|個入り|個セット|包入り|包|袋入り|袋|パック|セット|set|sets|pcs|pack|pk)",
    re.IGNORECASE,
)

# "× 5", "x 5", "*5" 패턴 (수량 X 개수)
_MUL_PATTERN = re.compile(r"[×xX*]\s*(\d{1,2})\b")

# "1+1", "2+1" 행사 → 합 (1+1=2, 2+1=3)
_PLUS_PATTERN = re.compile(r"(\d{1,2})\s*\+\s*(\d{1,2})")


def _regex_extract(name: str) -> int | None:
    """정규식으로 빠르게 추출. 명백하지 않으면 None (LLM 폴백)."""
    if not name:
        return None

    # "1+1" 류 행사
    m = _PLUS_PATTERN.search(name)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= 9 and 1 <= b <= 9:  # 행사 표기는 작은 숫자만
            total = a + b
            if _MIN <= total <= _MAX:
                return total

    # "N단위" 패턴
    m = _UNIT_PATTERN.search(name)
    if m:
        n = int(m.group(1))
        if _MIN <= n <= _MAX:
            return n

    # "× N" 패턴 (단위 없이)
    m = _MUL_PATTERN.search(name)
    if m:
        n = int(m.group(1))
        if _MIN <= n <= _MAX:
            return n

    return None


def _parse_int(text: str) -> int | None:
    """LLM 응답에서 첫 정수 추출. 1~99 범위 검증."""
    if not text:
        return None
    m = re.search(r"-?\d+", text)
    if not m:
        return None
    try:
        n = int(m.group(0))
    except ValueError:
        return None
    return n if _MIN <= n <= _MAX else None


async def extract_set_count_async(product_name: str) -> int:
    name = (product_name or "").strip()
    if not name:
        return _FALLBACK

    # 1) 정규식
    n = _regex_extract(name)
    if n is not None:
        return n

    # 2) LLM 폴백
    try:
        client = get_client_for("set_count")
    except Exception as e:
        logger.error(f"[set_count] 클라이언트 생성 실패 ({e}) → 1 폴백")
        return _FALLBACK

    template = load_prompt("set_count_extraction")
    prompt = template.replace("{product_name}", name)

    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=256,  # Gemini 2.5 thinking 토큰 + 숫자 출력 여유
        )
    except Exception as e:
        logger.error(f"[set_count] LLM 호출 실패 ({e}) → 1 폴백")
        return _FALLBACK

    parsed = _parse_int(result.text)
    if parsed is None:
        logger.info(f"[set_count] LLM 응답 정수 추출 실패 → 1 폴백: {result.text[:60]!r}")
        return _FALLBACK
    return parsed


def extract_set_count(product_name: str) -> int:
    """동기 래퍼 — CLI / 검증용."""
    return run_sync(extract_set_count_async(product_name))


__all__ = ["extract_set_count", "extract_set_count_async"]
