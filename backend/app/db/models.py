from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Keyword(Base):
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword_jp = Column(String, nullable=False)
    keyword_kr = Column(String)
    lookup_date = Column(Date, default=date.today)
    category = Column(String)
    classification = Column(String)  # 원본/유사/연관
    rank = Column(Integer)
    index_key = Column(String)
    competition_intensity = Column(Float)
    search_volume_weekly = Column(Integer)
    search_volume_daily = Column(Integer)
    total_products = Column(Integer)
    products_jp = Column(Integer)
    products_kr = Column(Integer)
    products_cn = Column(Integer)
    products_other = Column(Integer)
    volume_change_flag = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class VolumeHistory(Base):
    __tablename__ = "volume_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lookup_date = Column(Date, default=date.today)
    index_key = Column(String)
    keyword_jp = Column(String)
    competition_intensity = Column(Float)
    search_volume_weekly = Column(Integer)
    search_volume_daily = Column(Integer)
    total_products = Column(Integer)
    products_jp = Column(Integer)
    products_kr = Column(Integer)
    products_cn = Column(Integer)
    products_other = Column(Integer)


class BidHistory(Base):
    __tablename__ = "bid_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lookup_date = Column(Date, default=date.today)
    index_key = Column(String)
    keyword_jp = Column(String)
    related_keyword_count = Column(Integer)
    bid_count = Column(Integer)
    search_volume_weekly = Column(Integer)
    search_volume_daily = Column(Integer)
    bid_price_1 = Column(Integer)
    bid_price_2 = Column(Integer)
    bid_price_3 = Column(Integer)
    bid_price_4 = Column(Integer)
    bid_price_5 = Column(Integer)
    bid_price_6 = Column(Integer)
    bid_price_7 = Column(Integer)
    bid_price_8 = Column(Integer)
    bid_price_9 = Column(Integer)
    bid_price_10 = Column(Integer)


class TrackingItem(Base):
    __tablename__ = "tracking_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String, nullable=False)
    keyword = Column(String, nullable=False)
    product_name = Column(String)
    cover_image_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    histories = relationship("TrackingHistory", back_populates="tracking_item")


class TrackingHistory(Base):
    __tablename__ = "tracking_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_item_id = Column(Integer, ForeignKey("tracking_items.id"))
    lookup_date = Column(Date, default=date.today)
    rank_position = Column(Integer)
    tracking_item = relationship("TrackingItem", back_populates="histories")


class Qoo10Product(Base):
    __tablename__ = "qoo10_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_keyword = Column(String)
    product_name = Column(String)
    price_jpy = Column(Integer)
    shipping_fee = Column(String)
    origin = Column(String)
    cover_image_url = Column(String)
    product_url = Column(String)
    lookup_date = Column(Date, default=date.today)


class DomesticProduct(Base):
    __tablename__ = "domestic_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String)  # "coupang" or "naver"
    search_keyword = Column(String)
    product_name = Column(String)
    price_krw = Column(Integer)
    price_usd = Column(Float)
    shipping_fee = Column(String)
    origin = Column(String)
    cover_image_url = Column(String)
    product_url = Column(String)
    lookup_date = Column(Date, default=date.today)


class BestsellerItem(Base):
    __tablename__ = "bestseller_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String)
    category_code = Column(Integer)
    rank = Column(Integer)
    product_name = Column(String)
    brand = Column(String)
    price_jpy = Column(Integer)
    shipping_fee = Column(String)
    origin = Column(String)
    cover_image_url = Column(String)
    product_url = Column(String)
    sales_volume = Column(Integer)
    lookup_date = Column(Date, default=date.today)


class UserData(Base):
    """범용 JSON 저장: 시트·관심 키워드·샵 캐시 등을 PC 간 공유."""
    __tablename__ = "user_data"

    key = Column(String, primary_key=True)
    data = Column(Text)  # JSON 문자열
    updated_at = Column(DateTime, default=datetime.utcnow)
