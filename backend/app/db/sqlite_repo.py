from datetime import date
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import (
    KeywordRepository, BidRepository, ProductRepository,
    TrackingRepository, BestsellerRepository,
)
from app.db.models import (
    Keyword, VolumeHistory, BidHistory,
    Qoo10Product, DomesticProduct,
    TrackingItem, TrackingHistory,
    BestsellerItem,
)


class SQLiteKeywordRepository(KeywordRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_keywords(self, keywords: list[dict]) -> None:
        if not keywords:
            return

        # 동일 index_key (날짜_카테고리_분류_순위)를 가진 기존 행 삭제 후 새로 적재.
        # → 같은 일자에 동일 카테고리 재수집 시 중복 누적 방지, 최신값으로 갱신.
        keys = [kw["index_key"] for kw in keywords if kw.get("index_key")]
        if keys:
            # IN 절 너무 길면 분할
            chunk = 500
            for i in range(0, len(keys), chunk):
                await self.session.execute(
                    delete(Keyword).where(Keyword.index_key.in_(keys[i:i+chunk]))
                )

        for kw in keywords:
            self.session.add(Keyword(**kw))
        await self.session.commit()

    async def get_keywords(self, lookup_date: Optional[date] = None) -> list[dict]:
        stmt = select(Keyword).order_by(Keyword.id.desc())
        if lookup_date:
            stmt = stmt.where(Keyword.lookup_date == lookup_date)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            {c.name: getattr(r, c.name) for c in Keyword.__table__.columns}
            for r in rows
        ]

    async def delete_keyword(self, keyword_id: int) -> None:
        await self.session.execute(delete(Keyword).where(Keyword.id == keyword_id))
        await self.session.commit()

    async def delete_by_date(self, lookup_date: date) -> int:
        result = await self.session.execute(
            delete(Keyword).where(Keyword.lookup_date == lookup_date)
        )
        await self.session.commit()
        return result.rowcount or 0

    async def list_dates(self) -> list[dict]:
        from sqlalchemy import func
        stmt = (
            select(Keyword.lookup_date, func.count(Keyword.id).label("count"))
            .group_by(Keyword.lookup_date)
            .order_by(Keyword.lookup_date.desc())
        )
        result = await self.session.execute(stmt)
        return [{"lookup_date": r[0], "count": r[1]} for r in result.all()]

    async def save_volume_history(self, records: list[dict]) -> None:
        for rec in records:
            self.session.add(VolumeHistory(**rec))
        await self.session.commit()

    async def get_volume_history(self, keyword_jp: Optional[str] = None) -> list[dict]:
        stmt = select(VolumeHistory).order_by(VolumeHistory.lookup_date.desc())
        if keyword_jp:
            stmt = stmt.where(VolumeHistory.keyword_jp == keyword_jp)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            {c.name: getattr(r, c.name) for c in VolumeHistory.__table__.columns}
            for r in rows
        ]


class SQLiteBidRepository(BidRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_bid_history(self, records: list[dict]) -> None:
        for rec in records:
            self.session.add(BidHistory(**rec))
        await self.session.commit()

    async def get_bid_history(self, keyword_jp: Optional[str] = None) -> list[dict]:
        stmt = select(BidHistory).order_by(BidHistory.lookup_date.desc())
        if keyword_jp:
            stmt = stmt.where(BidHistory.keyword_jp == keyword_jp)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            {c.name: getattr(r, c.name) for c in BidHistory.__table__.columns}
            for r in rows
        ]


class SQLiteProductRepository(ProductRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_qoo10_products(self, products: list[dict]) -> None:
        for p in products:
            self.session.add(Qoo10Product(**p))
        await self.session.commit()

    async def get_qoo10_products(self, search_keyword: Optional[str] = None) -> list[dict]:
        stmt = select(Qoo10Product).order_by(Qoo10Product.id.desc())
        if search_keyword:
            stmt = stmt.where(Qoo10Product.search_keyword == search_keyword)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            {c.name: getattr(r, c.name) for c in Qoo10Product.__table__.columns}
            for r in rows
        ]

    async def save_domestic_products(self, products: list[dict]) -> None:
        for p in products:
            self.session.add(DomesticProduct(**p))
        await self.session.commit()

    async def get_domestic_products(self, source: Optional[str] = None) -> list[dict]:
        stmt = select(DomesticProduct).order_by(DomesticProduct.id.desc())
        if source:
            stmt = stmt.where(DomesticProduct.source == source)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            {c.name: getattr(r, c.name) for c in DomesticProduct.__table__.columns}
            for r in rows
        ]


class SQLiteTrackingRepository(TrackingRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_tracking_item(self, item: dict) -> int:
        obj = TrackingItem(**item)
        self.session.add(obj)
        await self.session.commit()
        await self.session.refresh(obj)
        return obj.id

    async def get_tracking_items(self) -> list[dict]:
        stmt = select(TrackingItem).order_by(TrackingItem.id)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            {c.name: getattr(r, c.name) for c in TrackingItem.__table__.columns}
            for r in rows
        ]

    async def save_tracking_history(self, records: list[dict]) -> None:
        for rec in records:
            self.session.add(TrackingHistory(**rec))
        await self.session.commit()

    async def get_tracking_history(self, tracking_item_id: int) -> list[dict]:
        stmt = (
            select(TrackingHistory)
            .where(TrackingHistory.tracking_item_id == tracking_item_id)
            .order_by(TrackingHistory.lookup_date.desc())
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            {c.name: getattr(r, c.name) for c in TrackingHistory.__table__.columns}
            for r in rows
        ]


class SQLiteBestsellerRepository(BestsellerRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_bestseller_items(self, items: list[dict]) -> None:
        for item in items:
            self.session.add(BestsellerItem(**item))
        await self.session.commit()

    async def get_bestseller_items(self, category: Optional[str] = None) -> list[dict]:
        stmt = select(BestsellerItem).order_by(BestsellerItem.rank)
        if category:
            stmt = stmt.where(BestsellerItem.category == category)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            {c.name: getattr(r, c.name) for c in BestsellerItem.__table__.columns}
            for r in rows
        ]
