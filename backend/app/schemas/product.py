from datetime import date
from typing import Optional

from pydantic import BaseModel


class Qoo10ProductOut(BaseModel):
    id: int
    search_keyword: Optional[str] = None
    product_name: Optional[str] = None
    price_jpy: Optional[int] = None
    shipping_fee: Optional[str] = None
    origin: Optional[str] = None
    cover_image_url: Optional[str] = None
    product_url: Optional[str] = None
    lookup_date: Optional[date] = None


class DomesticProductOut(BaseModel):
    id: int
    source: Optional[str] = None
    search_keyword: Optional[str] = None
    product_name: Optional[str] = None
    price_krw: Optional[int] = None
    price_usd: Optional[float] = None
    shipping_fee: Optional[str] = None
    origin: Optional[str] = None
    cover_image_url: Optional[str] = None
    product_url: Optional[str] = None
    lookup_date: Optional[date] = None


class ProductSearchRequest(BaseModel):
    keyword: str


class BestsellerItemOut(BaseModel):
    id: int
    category: Optional[str] = None
    category_code: Optional[int] = None
    rank: Optional[int] = None
    product_name: Optional[str] = None
    brand: Optional[str] = None
    price_jpy: Optional[int] = None
    shipping_fee: Optional[str] = None
    origin: Optional[str] = None
    cover_image_url: Optional[str] = None
    product_url: Optional[str] = None
    sales_volume: Optional[int] = None
    lookup_date: Optional[date] = None
