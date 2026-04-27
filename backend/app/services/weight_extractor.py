"""상품명/OCR 텍스트에서 무게(g) 추출 + 200g 패키지 룰.

흐름 (Phase 4-A):
    1) 상품명 정규식 — 「100g」「3g×40개」「1.5kg」「500ml」 등
    2) OCR fallback (별도) — cover image easyocr → 같은 정규식
    3) 둘 다 실패 → None (사장님 시트에서 수동 입력)
    4) 추출 무게 + 200g 패키지 가중치 (사장님 명세 4-3)

ml ↔ g: 1ml ≈ 1g (액체 한정 근사. 화장품/식품 모두 OK)

반환:
    extract_weight_grams(text) → float | None  (raw weight in grams, +200g 미적용)
    apply_packaging_rule(g)   → float          (raw_g + 200, 최소 200g)
"""
from __future__ import annotations

import re
from typing import Optional

# 단위 정규화 (소문자 비교)
_UNIT_TO_G: dict[str, float] = {
    "kg": 1000.0,
    "g": 1.0,
    "그램": 1.0,
    "그람": 1.0,
    "l": 1000.0,    # 1 L ≈ 1000 g (액체 근사)
    "ml": 1.0,      # 1 ml ≈ 1 g
    "리터": 1000.0,
    "milliliter": 1.0,
}

# (?i) 케이스 무시. 단위 앞 숫자 + 옵션 곱셈 (×N개 / xN팩 / N입)
# 예: "3g x 40개", "5gx30포", "100ml"
_PATTERN_MULT = re.compile(
    r"(?P<n>\d+(?:[.,]\d+)?)\s*(?P<u>kg|g|ml|l|그램|그람|리터)"
    r"\s*(?:[×xX*]\s*(?P<m>\d+))?",
    re.IGNORECASE,
)

# 「N개입」「N입」「N포」 — 단독으로는 무게 X
# 곱셈 패턴 없이 「3개입」 만 있는 경우 weight 미상 (정규식 매칭 X)


def _parse_number(s: str) -> Optional[float]:
    s = (s or "").replace(",", ".").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def extract_weight_grams(text: str) -> Optional[float]:
    """텍스트에서 무게(g) 추출.

    매칭 우선순위:
      1) 가장 큰 무게 (kg > g, 곱셈 적용)
      2) 곱셈 토큰 있으면 N×m
      3) 단순 단일 토큰

    실패 시 None.
    """
    if not text:
        return None

    candidates: list[float] = []
    for m in _PATTERN_MULT.finditer(text):
        n = _parse_number(m.group("n"))
        unit = (m.group("u") or "").lower()
        per_unit_g = _UNIT_TO_G.get(unit)
        if n is None or per_unit_g is None:
            continue
        weight = n * per_unit_g
        # 곱셈 (×40개)
        mult = m.group("m")
        if mult:
            try:
                k = int(mult)
                if 1 <= k <= 200:    # 비현실적 곱셈 차단
                    weight *= k
            except (ValueError, TypeError):
                pass
        # 비현실 무게 차단 (1g 미만, 100kg 초과)
        if 1.0 <= weight <= 100_000:
            candidates.append(weight)

    if not candidates:
        return None
    # 가장 큰 후보 — 보통 「전체 무게」가 가장 의미 있음
    return max(candidates)


def apply_packaging_rule(raw_grams: Optional[float], packaging_g: float = 200.0) -> Optional[float]:
    """+200g 패키지 룰 (사장님 명세 4-3).

    raw_grams=None 이면 None 반환 (caller 가 수동 입력 처리).
    raw_grams 가 있으면 raw + packaging_g, 최소 packaging_g.
    """
    if raw_grams is None:
        return None
    if raw_grams < 0:
        raw_grams = 0.0
    return raw_grams + packaging_g


def extract_and_apply(text: str, packaging_g: float = 200.0) -> tuple[Optional[float], Optional[float]]:
    """편의 — (raw_g, registered_g) 동시 반환."""
    raw = extract_weight_grams(text)
    return raw, apply_packaging_rule(raw, packaging_g)


__all__ = ["extract_weight_grams", "apply_packaging_rule", "extract_and_apply"]
