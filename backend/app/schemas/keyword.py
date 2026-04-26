from datetime import date
from typing import Optional

from pydantic import BaseModel


class KeywordOut(BaseModel):
    id: int
    keyword_jp: str
    keyword_kr: Optional[str] = None
    lookup_date: Optional[date] = None
    category: Optional[str] = None
    classification: Optional[str] = None
    rank: Optional[int] = None
    index_key: Optional[str] = None
    competition_intensity: Optional[float] = None
    search_volume_weekly: Optional[int] = None
    search_volume_daily: Optional[int] = None
    total_products: Optional[int] = None
    products_jp: Optional[int] = None
    products_kr: Optional[int] = None
    products_cn: Optional[int] = None
    products_other: Optional[int] = None
    volume_change_flag: Optional[str] = None


class KeywordAddRequest(BaseModel):
    keyword_jp: str
    keyword_kr: Optional[str] = None


class TrendKeywordRequest(BaseModel):
    category: int | None = None  # 단일 선택 (하위 호환)
    categories: list[int] | None = None  # 다중 선택 (예: [1,3,5]) — 비어있거나 0 포함이면 전체
    fill_total_products: bool = True
    translate: bool = True
    collect_bids: bool = False  # 광고 경매 낙찰가 수집 여부 (오래 걸림 — 기본 OFF)


class RelatedKeywordRequest(BaseModel):
    keywords: list[str]


class CompetitionRequest(BaseModel):
    keywords: list[str]
