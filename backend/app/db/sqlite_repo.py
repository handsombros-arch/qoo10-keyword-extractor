import logging
import os
from datetime import date
from typing import Optional

from sqlalchemy import select, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

_kw_logger = logging.getLogger("db.keywords")

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

BID_COLUMNS = (
    "bid_count",
    "bid_price_1", "bid_price_2", "bid_price_3", "bid_price_4", "bid_price_5",
    "bid_price_6", "bid_price_7", "bid_price_8", "bid_price_9", "bid_price_10",
)


class SQLiteKeywordRepository(KeywordRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_keywords(self, keywords: list[dict]) -> None:
        if not keywords:
            return

        # (lookup_date, category, classification) 조합별 기존 행 삭제 후 적재.
        #   같은 조합 재수집 시 과거 rank(31~100 등) 잔재 제거가 목적.
        # ── 데이터 안전가드 (R: 당일 데이터 자동 파괴 방지) ──
        #   매일 자동 수집이 부분/0건 실패하면 적은 행으로 기존 양호 데이터를 덮어쓸 수 있다.
        #   → 조합별 "새 배치 행수"가 "기존 행수 × ratio" 미만이면 그 조합은 삭제·적재 모두 스킵
        #     (기존 보존). 큐텐은 과거 일자 복구 불가하므로 보존이 우선.
        combo_new: dict[tuple, int] = {}
        for kw in keywords:
            d = kw.get("lookup_date")
            c = kw.get("category")
            cls = kw.get("classification")
            if d and c and cls:
                key = (d, c, cls)
                combo_new[key] = combo_new.get(key, 0) + 1

        try:
            ratio = float(os.getenv("KEYWORD_SAVE_GUARD_RATIO", "0.5"))
        except (TypeError, ValueError):
            ratio = 0.5

        skipped: set[tuple] = set()
        for (d, c, cls), n_new in combo_new.items():
            existing = await self.session.scalar(
                select(func.count(Keyword.id)).where(
                    and_(
                        Keyword.lookup_date == d,
                        Keyword.category == c,
                        Keyword.classification == cls,
                    )
                )
            ) or 0
            if existing > 0 and n_new < existing * ratio:
                # 급감 — 부분수집/실패 의심 → 기존 보존
                skipped.add((d, c, cls))
                _kw_logger.warning(
                    f"[save_keywords 데이터보호] {d}/{c}/{cls}: 새 {n_new} < 기존 {existing}×{ratio:g} "
                    f"→ 삭제·적재 스킵(기존 보존). 부분수집/실패 의심."
                )
            else:
                await self.session.execute(
                    delete(Keyword).where(
                        and_(
                            Keyword.lookup_date == d,
                            Keyword.category == c,
                            Keyword.classification == cls,
                        )
                    )
                )

        inserted = 0
        for kw in keywords:
            key = (kw.get("lookup_date"), kw.get("category"), kw.get("classification"))
            if key in skipped:
                continue  # 보호된 조합은 적재 안 함 (기존 유지)
            self.session.add(Keyword(**kw))
            inserted += 1
        await self.session.commit()
        if skipped:
            _kw_logger.warning(
                f"[save_keywords] 데이터보호로 {len(skipped)}개 조합 스킵, {inserted}개 적재 "
                f"(원본 키워드 {len(keywords)}개 중)."
            )

    async def get_keywords(self, lookup_date: Optional[date] = None) -> list[dict]:
        stmt = select(Keyword).order_by(Keyword.id.desc())
        if lookup_date:
            stmt = stmt.where(Keyword.lookup_date == lookup_date)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        # (lookup_date, keyword_jp) → BidHistory 최신 1건 맵 생성
        bid_map: dict[tuple, BidHistory] = {}
        if rows:
            pairs = {(r.lookup_date, r.keyword_jp) for r in rows if r.lookup_date and r.keyword_jp}
            if pairs:
                dates = {p[0] for p in pairs}
                kws = {p[1] for p in pairs}
                bid_stmt = (
                    select(BidHistory)
                    .where(BidHistory.lookup_date.in_(dates))
                    .where(BidHistory.keyword_jp.in_(kws))
                    .order_by(BidHistory.id.desc())
                )
                bid_result = await self.session.execute(bid_stmt)
                for b in bid_result.scalars().all():
                    key = (b.lookup_date, b.keyword_jp)
                    if key not in bid_map:  # id 내림차순이라 최신 1건 유지
                        bid_map[key] = b

        out = []
        for r in rows:
            row_dict = {c.name: getattr(r, c.name) for c in Keyword.__table__.columns}
            b = bid_map.get((r.lookup_date, r.keyword_jp))
            for col in BID_COLUMNS:
                row_dict[col] = getattr(b, col, None) if b else None
            out.append(row_dict)
        return out

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

    async def replace_bid_history(self, lookup_date: date, records: list[dict]) -> None:
        """같은 (lookup_date, keyword_jp) 기존 행 삭제 후 적재 — 중복 누적 방지."""
        if not records:
            return
        kws = [rec.get("keyword_jp") for rec in records if rec.get("keyword_jp")]
        if kws:
            chunk = 500
            for i in range(0, len(kws), chunk):
                await self.session.execute(
                    delete(BidHistory).where(
                        and_(
                            BidHistory.lookup_date == lookup_date,
                            BidHistory.keyword_jp.in_(kws[i:i + chunk]),
                        )
                    )
                )
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
