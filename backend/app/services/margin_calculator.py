"""
큐텐 마진 계산 모듈.

원본: 글로벌라이징-큐텐 판매제품리스트.xlsx (3월판매상품 시트).
원본 수식의 "이중 환율"(이익은 ×10, 마진율은 ×환율)을 그대로 재현한다.
정확 환율만 쓰고 싶으면 use_exact_rate=True.

사용자 비즈니스 규칙 (2026-04-20):
- 단가 < 20,000원: 유료배송(Tracx) — 바이어가 배송비 부담
- 단가 ≥ 20,000원: 무료배송(KSE) — 셀러가 배송비 부담
- 마진이 낮으면 2개/3개 세트 구성 제안 (배송비 규모 효과)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "qoo10_shipping_rates.json"

QOO10_COMMISSION_RATE = 0.135
MEGAWARI_DISCOUNT = 0.9
DEFAULT_MARGIN_MULTIPLIER = 1.3
APPROX_RATE = 10
FREE_SHIPPING_THRESHOLD_KRW = 20000  # 단가 기준: 이 금액 이상이면 무료배송


def _load_tables() -> dict:
    with _DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


_TABLES = _load_tables()


ShippingMode = Literal["auto", "free", "paid"]


def _lookup_kse_shipping(weight_g: float) -> float:
    """KSE 배송비(원) 조회. 유료·무료 모두 이 테이블 기준."""
    table = _TABLES["free_kse"]
    if weight_g <= 0:
        return 0.0
    for row in table:
        if weight_g <= row["weight_g"]:
            return row["shipping_krw"]
    return table[-1]["shipping_krw"]


def _resolve_shipping_mode(sell_price_krw: float, mode: ShippingMode) -> Literal["free", "paid"]:
    if mode == "auto":
        return "free" if sell_price_krw >= FREE_SHIPPING_THRESHOLD_KRW else "paid"
    return mode


@dataclass
class MarginResult:
    # 입력 메타
    weight_g: float
    purchase_price_krw: float
    shipping_packaging_krw: float
    sell_price_jpy: float
    exchange_rate: float
    is_mega: bool
    quantity: int = 1
    composition_label: str = "단품"
    shipping_mode_resolved: str = "free_kse"

    # 계산 결과
    effective_sell_jpy: float = 0.0
    commission_jpy: float = 0.0
    shipping_cost_krw: float = 0.0
    revenue_krw: float = 0.0
    total_cost_krw: float = 0.0
    profit_krw: float = 0.0
    margin_rate: float = 0.0

    # 참고값
    recommended_price_krw_30pct: float = 0.0


@dataclass
class CompositionOption:
    label: str
    quantity: int
    price_multiplier: float  # 단품 대비 판매가 배수 (예: 2개 세트 = 1.8)


DEFAULT_COMPOSITIONS: list[CompositionOption] = [
    CompositionOption(label="단품", quantity=1, price_multiplier=1.0),
    CompositionOption(label="2개 세트", quantity=2, price_multiplier=1.8),   # 개당 10% 할인
    CompositionOption(label="3개 세트", quantity=3, price_multiplier=2.55),  # 개당 15% 할인
]


def calculate_qoo10_margin(
    weight_g: float,
    purchase_price_krw: float,
    shipping_packaging_krw: float,
    sell_price_jpy: float,
    is_mega: bool = False,
    exchange_rate: float = 9.5,
    use_exact_rate: bool = False,
    shipping_mode: ShippingMode = "auto",
    quantity: int = 1,
    composition_label: str = "단품",
    price_multiplier: float = 1.0,
) -> MarginResult:
    """큐텐 마진 계산.

    quantity/price_multiplier: 구성 시뮬레이션용. 단품은 quantity=1, multiplier=1.0.
    shipping_mode="auto"면 (단품 기준 원화 판매가)가 20,000원 이상일 때 무료(KSE), 미만이면 유료(Tracx).
    """
    rate = exchange_rate if use_exact_rate else APPROX_RATE

    # 구성 적용: 수량만큼 무게/원가/국내배송 곱함, 판매가는 multiplier 곱함
    effective_weight = weight_g * quantity
    effective_purchase = purchase_price_krw * quantity
    effective_shipping_packaging = shipping_packaging_krw * quantity
    base_sell_jpy = sell_price_jpy * price_multiplier

    # 메가와리 할인
    effective_jpy = base_sell_jpy * (MEGAWARI_DISCOUNT if is_mega else 1.0)

    # 배송 모드 결정 (원화 기준 판매가로 판정)
    sell_price_krw_for_mode = effective_jpy * exchange_rate  # 모드 판정은 항상 정확환율
    resolved_mode = _resolve_shipping_mode(sell_price_krw_for_mode, shipping_mode)

    # 유료: 바이어가 배송비 부담 → 셀러 비용 0
    # 무료: 셀러가 KSE 배송비 부담
    # 두 경우 모두 배송 실비는 KSE 요금표 기준.
    if resolved_mode == "paid":
        shipping_cost_krw = 0.0
    else:
        shipping_cost_krw = _lookup_kse_shipping(effective_weight)

    # 수수료
    commission_jpy = effective_jpy * QOO10_COMMISSION_RATE

    # 원가/매출/이익
    revenue_krw = effective_jpy * rate
    commission_krw = commission_jpy * rate
    total_cost_krw = effective_purchase + effective_shipping_packaging + commission_krw + shipping_cost_krw
    profit_krw = revenue_krw - total_cost_krw

    # 마진율 — 원본 시트처럼 "정확환율 기준 매출"으로 계산
    margin_rate = profit_krw / (base_sell_jpy * exchange_rate) if base_sell_jpy > 0 else 0.0

    recommended = (effective_purchase + effective_shipping_packaging) * DEFAULT_MARGIN_MULTIPLIER

    return MarginResult(
        weight_g=weight_g,
        purchase_price_krw=purchase_price_krw,
        shipping_packaging_krw=shipping_packaging_krw,
        sell_price_jpy=sell_price_jpy,
        exchange_rate=exchange_rate,
        is_mega=is_mega,
        quantity=quantity,
        composition_label=composition_label,
        shipping_mode_resolved=resolved_mode,
        effective_sell_jpy=effective_jpy,
        commission_jpy=commission_jpy,
        shipping_cost_krw=shipping_cost_krw,
        revenue_krw=revenue_krw,
        total_cost_krw=total_cost_krw,
        profit_krw=profit_krw,
        margin_rate=margin_rate,
        recommended_price_krw_30pct=recommended,
    )


def calculate_both(
    weight_g: float,
    purchase_price_krw: float,
    shipping_packaging_krw: float,
    sell_price_jpy: float,
    exchange_rate: float = 9.5,
    use_exact_rate: bool = False,
    shipping_mode: ShippingMode = "auto",
) -> dict:
    """일반가 + 메가와리 두 시나리오."""
    common = dict(
        weight_g=weight_g, purchase_price_krw=purchase_price_krw,
        shipping_packaging_krw=shipping_packaging_krw, sell_price_jpy=sell_price_jpy,
        exchange_rate=exchange_rate, use_exact_rate=use_exact_rate, shipping_mode=shipping_mode,
    )
    return {
        "normal": calculate_qoo10_margin(**common, is_mega=False),
        "mega": calculate_qoo10_margin(**common, is_mega=True),
    }


def analyze_compositions(
    weight_g: float,
    purchase_price_krw: float,
    shipping_packaging_krw: float,
    sell_price_jpy: float,
    exchange_rate: float = 9.5,
    use_exact_rate: bool = False,
    shipping_mode: ShippingMode = "auto",
    compositions: list[CompositionOption] | None = None,
) -> list[MarginResult]:
    """단품·2개·3개 세트 구성 각각의 마진 계산. 일반가 기준."""
    comps = compositions or DEFAULT_COMPOSITIONS
    results = []
    for c in comps:
        r = calculate_qoo10_margin(
            weight_g=weight_g,
            purchase_price_krw=purchase_price_krw,
            shipping_packaging_krw=shipping_packaging_krw,
            sell_price_jpy=sell_price_jpy,
            is_mega=False,
            exchange_rate=exchange_rate,
            use_exact_rate=use_exact_rate,
            shipping_mode=shipping_mode,
            quantity=c.quantity,
            composition_label=c.label,
            price_multiplier=c.price_multiplier,
        )
        results.append(r)
    return results


def margin_verdict(margin_rate: float) -> str:
    """마진율 정성 평가."""
    if margin_rate >= 0.30:
        return "우수"
    if margin_rate >= 0.20:
        return "양호"
    if margin_rate >= 0.10:
        return "애매"
    if margin_rate >= 0.0:
        return "부족"
    return "손실"


def recommend_best_composition(results: list[MarginResult]) -> MarginResult:
    """마진율 최고 구성 반환."""
    return max(results, key=lambda r: r.margin_rate)
