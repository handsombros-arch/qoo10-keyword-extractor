from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.margin_calculator import (
    analyze_compositions,
    calculate_both,
    calculate_qoo10_margin,
    margin_verdict,
    recommend_best_composition,
)

router = APIRouter(prefix="/api/margin", tags=["margin"])


class MarginRequest(BaseModel):
    weight_g: float = Field(..., description="무료배송 기준 무게(g) = 실무게+100g")
    purchase_price_krw: float = Field(..., description="구매가(원)")
    shipping_packaging_krw: float = Field(..., description="KSE 배대지 배송비+포장비(원)")
    sell_price_jpy: float = Field(..., description="큐텐 판매가(엔)")
    exchange_rate: float = Field(9.5)
    use_exact_rate: bool = Field(False)
    shipping_mode: Literal["auto", "free_kse", "paid_tracx"] = Field("auto", description="auto=단가20000원 기준 자동")


@router.post("/calculate")
async def calculate(req: MarginRequest):
    """일반가 + 메가와리 두 시나리오 동시 계산."""
    result = calculate_both(**req.dict())
    normal = result["normal"]
    mega = result["mega"]
    return {
        "normal": {**asdict(normal), "verdict": margin_verdict(normal.margin_rate)},
        "mega": {**asdict(mega), "verdict": margin_verdict(mega.margin_rate)},
    }


@router.post("/analyze-compositions")
async def analyze(req: MarginRequest):
    """단품/2개/3개 구성별 마진 분석. 추천 구성 반환."""
    results = analyze_compositions(
        weight_g=req.weight_g,
        purchase_price_krw=req.purchase_price_krw,
        shipping_packaging_krw=req.shipping_packaging_krw,
        sell_price_jpy=req.sell_price_jpy,
        exchange_rate=req.exchange_rate,
        use_exact_rate=req.use_exact_rate,
        shipping_mode=req.shipping_mode,
    )
    best = recommend_best_composition(results)
    return {
        "compositions": [
            {**asdict(r), "verdict": margin_verdict(r.margin_rate)} for r in results
        ],
        "best_composition_label": best.composition_label,
    }
