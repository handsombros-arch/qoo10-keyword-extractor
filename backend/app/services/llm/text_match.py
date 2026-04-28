"""상품명 텍스트 유사도 매칭 (LLM 호출 없음, 순수 토큰 기반).

용도:
    큐텐 product_name_ko ↔ 한국 product_name 의 매칭 점수 0~1.
    이미지 매칭(image_match.py) 과 AND 결합해 광고 키워드 도용
    (예: 「하파크리스틴」 키워드로 IVE 포토카드 등록) 자동 거부.

알고리즘:
    1) 양쪽 텍스트 토큰화 (공백/구두점/특수문자 split, lowercase, 길이 ≥ 2)
    2) Jaccard 유사도 = |A ∩ B| / |A ∪ B|
    3) 부분문자열 보너스: A 토큰이 B 토큰의 substring 이거나 그 역이면 hit
       (브랜드 변형 「메디큐브」 vs 「메디큐브에이지컷」 등 흡수)
    4) 결과 score = jaccard ⊕ partial — 0.0 ~ 1.0 클램프

env: TEXT_MATCH_THRESHOLD=0.3 (caller 가 사용)

사용:
    score = name_similarity("메디큐브 제로 모공패드 70매", "메디큐브 에이지컷 70매")
    # ≈ 0.45 (브랜드+개수 토큰 일치)
"""
from __future__ import annotations

import re

# 토큰 구분자 — 공백 + 흔한 구두점/특수문자.
# 이미 일본어 구두점 (・「」【】) 도 포함.
_SPLIT_RE = re.compile(
    r"[\s\-_/\\,\.\!\?\(\)\[\]\{\}\|:;\+\*=&\^%\$#@~`'\"<>"
    r"·、。「」『』【】〈〉《》〔〕［］｛｝（）]+"
)

# 의미 없는 한 글자 / 흔한 stopword (상품명 매칭에서 노이즈)
_STOPWORDS = {
    "set", "pack", "box", "ml", "g", "kg", "mg", "oz", "lb",
    "the", "a", "an", "of", "and", "or", "for",
    "정품", "정규품", "공식", "공식정품", "한국", "韓国", "韓國",
    "일본", "日本", "신상", "신작", "특가", "할인",
    # SEO 광고 노이즈 (한국 셀러가 검색 유입용으로 product_name 에 끼워넣는 단어)
    "공구", "공동구매", "도매", "직배송", "박스째", "포상", "선물",
    "체험", "미안기", "취급", "설명서", "스킨", "샴푸", "케어",
    "fedex", "정규", "리프팅", "안티에이징", "신제품", "k-뷰티", "kbeauty",
    "특별", "프리미엄", "공구함", "당일발송", "당일출고", "오늘출발",
    "사은품", "해외배송", "한정판", "단독", "프로모션", "이벤트",
    "최저가", "가성비", "추천", "베스트", "인기", "1+1", "2+1",
}


def _tokenize(s: str) -> set[str]:
    """상품명 → 매칭용 토큰 set.

    - 소문자화
    - 길이 ≥ 2
    - 숫자 단독은 유지 (수량/용량 매칭에 도움)
    - stopwords 제거
    """
    if not s:
        return set()
    parts = _SPLIT_RE.split(s.lower())
    out: set[str] = set()
    for p in parts:
        p = p.strip()
        if not p or len(p) < 2:
            continue
        if p in _STOPWORDS:
            continue
        out.add(p)
    return out


def _partial_overlap(a: set[str], b: set[str]) -> int:
    """A 와 B 의 토큰 쌍 중 substring 관계인 쌍의 개수 (정확 일치 제외)."""
    n = 0
    a_only = a - b
    b_only = b - a
    for ta in a_only:
        if len(ta) < 3:
            continue
        for tb in b_only:
            if len(tb) < 3:
                continue
            if ta in tb or tb in ta:
                n += 1
                break  # ta 한 번 카운트
    return n


def name_similarity(text_a: str, text_b: str) -> float:
    """두 상품명 텍스트의 매칭 점수 0.0 ~ 1.0.

    공집합/한쪽 빈 입력 → 0.0.

    score = (|A ∩ B| + 0.5 × partial) / |A ∪ B|

    - 정확히 일치하는 토큰 1개당 가중치 1.0
    - substring 관계 토큰 1쌍당 가중치 0.5 (브랜드 변형 흡수)
    - 분모는 합집합 → 너무 짧은 상품명에서 100% 가짜 매칭 방지
    """
    a = _tokenize(text_a)
    b = _tokenize(text_b)
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    partial = _partial_overlap(a, b)
    score = (len(inter) + 0.5 * partial) / max(len(union), 1)
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return round(score, 4)


__all__ = ["name_similarity"]
