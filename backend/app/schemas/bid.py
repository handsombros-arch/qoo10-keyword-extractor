from datetime import date
from typing import Optional

from pydantic import BaseModel


class BidHistoryOut(BaseModel):
    id: int
    lookup_date: Optional[date] = None
    index_key: Optional[str] = None
    keyword_jp: Optional[str] = None
    related_keyword_count: Optional[int] = None
    bid_count: Optional[int] = None
    search_volume_weekly: Optional[int] = None
    search_volume_daily: Optional[int] = None
    bid_price_1: Optional[int] = None
    bid_price_2: Optional[int] = None
    bid_price_3: Optional[int] = None
    bid_price_4: Optional[int] = None
    bid_price_5: Optional[int] = None
    bid_price_6: Optional[int] = None
    bid_price_7: Optional[int] = None
    bid_price_8: Optional[int] = None
    bid_price_9: Optional[int] = None
    bid_price_10: Optional[int] = None


class BidCollectRequest(BaseModel):
    keywords: list[str]
