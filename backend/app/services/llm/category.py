"""상품명 → 큐텐 카테고리 분류.

옵션 C (사장님 핵심 5분류 + 기타):
    - 03.뷰티&화장품
    - 06.홈&생활
    - 07.식품
    - 09.베이비&키즈
    - 12.서플리먼트&다이어트
    - 기타

라벨 키 형식은 m02_trend_keywords.CATEGORIES 와 동일 (번호.이름).
m02 의 카테고리 1/2/4/5/8/10/11 은 본 셀러 비즈니스 비핵심이라 모두 "기타" 로 흡수한다.

env: CATEGORY_MODEL=<provider:model>
prompt: app/services/llm/prompts/category_classification.txt

사용:
    # async (워크플로우용)
    label = await classify_category_async("아누아 어성초 토너")

    # sync (CLI 검증용)
    label = classify_category("아누아 어성초 토너")
"""
from __future__ import annotations

import json
import logging
import re

from ._sync import run_sync
from .router import get_client_for, load_prompt

logger = logging.getLogger(__name__)


# 큐텐 12개 분류 중 사장님 핵심 5개 + 기타
LABELS = [
    "03.뷰티&화장품",
    "06.홈&생활",
    "07.식품",
    "09.베이비&키즈",
    "12.서플리먼트&다이어트",
    "기타",
]
FALLBACK = "기타"

# 부분 매칭용 키워드. LLM이 라벨 일부만 답해도 (예: "뷰티&화장품", "뷰티") 흡수.
_PARTIAL_HINTS: list[tuple[str, str]] = [
    ("뷰티", "03.뷰티&화장품"),
    ("화장품", "03.뷰티&화장품"),
    ("서플리먼트", "12.서플리먼트&다이어트"),
    ("다이어트", "12.서플리먼트&다이어트"),
    ("베이비", "09.베이비&키즈"),
    ("키즈", "09.베이비&키즈"),
    ("식품", "07.식품"),
    ("홈&생활", "06.홈&생활"),
    ("홈생활", "06.홈&생활"),
    ("생활", "06.홈&생활"),
    ("기타", "기타"),
]


def _normalize_response(text: str) -> str:
    """LLM 응답을 LABELS 중 하나로 정규화. 매칭 실패 시 FALLBACK."""
    if not text:
        return FALLBACK

    raw = text.strip()
    # 첫 줄만 (LLM이 설명을 붙이는 경우 라벨이 첫 줄에 있다고 가정)
    first_line = raw.splitlines()[0].strip() if raw else ""

    # 1) 정확 매칭 (첫 줄 또는 전체)
    for candidate in (first_line, raw):
        for label in LABELS:
            if candidate == label:
                return label

    # 2) 라벨이 응답에 통째로 포함 (예: "분류: 03.뷰티&화장품")
    for label in LABELS:
        if label in raw:
            return label

    # 3) 부분 키워드 매칭 (긴 키워드 우선 — _PARTIAL_HINTS 정의 순서로 처리)
    for keyword, label in _PARTIAL_HINTS:
        if keyword in raw:
            return label

    logger.warning(f"[category] 응답 정규화 실패 → '기타' 폴백: {raw[:80]!r}")
    return FALLBACK


async def classify_category_async(
    product_name: str,
    examples: list[str] | None = None,
) -> str:
    """상품명/키워드를 큐텐 카테고리로 분류 (async).

    examples (선택): 같은 키워드의 큐텐/네이버 상품명 N개. 키워드가 브랜드 단독
    같이 짧을 때 컨텍스트로 활용 — 「メディキューブ」 단독이면 「기타」 폴백되던 결함 회피.

    빈 입력은 즉시 '기타' 반환 (LLM 호출 안 함).
    호출 실패 시 '기타' 반환 — 자동화 파이프라인을 막지 않는다.
    """
    name = (product_name or "").strip()
    if not name:
        return FALLBACK

    try:
        client = get_client_for("category")
    except Exception as e:
        logger.error(f"[category] 클라이언트 생성 실패 ({e}) → '기타' 폴백")
        return FALLBACK

    template = load_prompt("category_classification")
    # examples 블록 — 비면 빈 줄, 있으면 max 5건 한 줄씩
    examples_block = ""
    if examples:
        sample = [e.strip() for e in examples if e and e.strip()][:5]
        if sample:
            examples_block = "\n참고 상품명 (해당 키워드의 실제 상품 예시):\n" + "\n".join(
                f"- {s[:80]}" for s in sample
            )
    prompt = template.replace("{product_name}", name).replace("{examples_block}", examples_block)

    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True,   # JSON 강제 → Gemini 2.5 thinking 토큰 효율적 사용 (brand 와 동일 패턴)
            max_tokens=2048,
        )
    except Exception as e:
        logger.error(f"[category] LLM 호출 실패 ({e}) → '기타' 폴백")
        return FALLBACK

    # 빈/너무 짧은 응답 → thinking 토큰 부족 신호. raise → caller 가 DB UPDATE 스킵.
    text = (result.text or "").strip()
    if len(text) < 2:
        raise RuntimeError(
            f"empty/too-short LLM response "
            f"(len={len(text)}, in_tok={result.input_tokens}, out_tok={result.output_tokens})"
        )

    # JSON 파싱 — {"category": "라벨명"}. 실패하면 raw 텍스트로 _normalize_response 폴백.
    label_text = text
    s = re.sub(r"^```(?:json)?\s*", "", text)
    s = re.sub(r"\s*```\s*$", "", s)
    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict):
            label_text = (parsed.get("category") or "").strip() or text
    except json.JSONDecodeError:
        pass

    return _normalize_response(label_text)


def classify_category(product_name: str, examples: list[str] | None = None) -> str:
    """동기 래퍼 — CLI / 검증용.

    이미 event loop 안에서 호출되면 RuntimeError 가 난다 → 그땐 async 버전 직접 사용.
    """
    return run_sync(classify_category_async(product_name, examples))


__all__ = ["LABELS", "FALLBACK", "classify_category", "classify_category_async"]
