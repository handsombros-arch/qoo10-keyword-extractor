from datetime import date
from typing import Optional

from pydantic import BaseModel


class TrackingItemOut(BaseModel):
    id: int
    product_id: str
    keyword: str
    product_name: Optional[str] = None
    cover_image_url: Optional[str] = None


class TrackingItemCreate(BaseModel):
    product_id: str
    keyword: str
    product_name: Optional[str] = None


class TrackingHistoryOut(BaseModel):
    id: int
    tracking_item_id: int
    lookup_date: Optional[date] = None
    rank_position: Optional[int] = None
