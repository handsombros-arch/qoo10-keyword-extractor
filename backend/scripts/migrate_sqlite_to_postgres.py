"""
SQLite → PostgreSQL (Supabase) 1회용 데이터 이관 스크립트.

사용법:
  cd backend
  python scripts/migrate_sqlite_to_postgres.py

사전 조건:
  - backend/.env 에 DATABASE_URL=postgresql://... 설정됨
  - backend/data/qoo10.db 가 이관할 SQLite 파일
"""
import asyncio
import sys
from pathlib import Path

# Windows 콘솔에서 UTF-8 출력 강제
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# backend 디렉터리를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import (
    Base, Keyword, VolumeHistory, BidHistory,
    Qoo10Product, DomesticProduct,
    TrackingItem, TrackingHistory, BestsellerItem,
)


SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "qoo10.db"
SQLITE_URL = f"sqlite+aiosqlite:///{SQLITE_PATH}"

TABLES = [
    Keyword, VolumeHistory, BidHistory,
    Qoo10Product, DomesticProduct,
    TrackingItem, TrackingHistory, BestsellerItem,
]


async def copy_table(src_session: AsyncSession, dst_session: AsyncSession, model) -> int:
    result = await src_session.execute(select(model))
    rows = result.scalars().all()
    if not rows:
        return 0

    cols = [c.name for c in model.__table__.columns if c.name != "id"]
    for row in rows:
        data = {c: getattr(row, c) for c in cols}
        dst_session.add(model(**data))
    await dst_session.commit()
    return len(rows)


async def main():
    if not SQLITE_PATH.exists():
        print(f"❌ SQLite 파일 없음: {SQLITE_PATH}")
        return

    if "postgresql" not in settings.DATABASE_URL:
        print(f"❌ DATABASE_URL이 PostgreSQL이 아닙니다: {settings.DATABASE_URL}")
        print("   backend/.env에 DATABASE_URL=postgresql://... 설정하세요.")
        return

    print(f"📂 Source: {SQLITE_URL}")
    print(f"🎯 Target: {settings.DATABASE_URL.split('@')[-1]}")
    print()

    src_engine = create_async_engine(SQLITE_URL, echo=False)
    dst_engine = create_async_engine(
        settings.DATABASE_URL, echo=False,
        pool_pre_ping=True, pool_recycle=300,
    )

    # 1) Postgres에 테이블 생성
    print("📐 PostgreSQL 테이블 생성 중...")
    async with dst_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2) 데이터 복사
    src_factory = async_sessionmaker(src_engine, class_=AsyncSession, expire_on_commit=False)
    dst_factory = async_sessionmaker(dst_engine, class_=AsyncSession, expire_on_commit=False)

    total = 0
    for model in TABLES:
        try:
            async with src_factory() as src_session, dst_factory() as dst_session:
                n = await copy_table(src_session, dst_session, model)
                print(f"  ✓ {model.__tablename__}: {n}행 복사")
                total += n
        except Exception as e:
            print(f"  ❌ {model.__tablename__}: {e}")

    print()
    print(f"✅ 총 {total}행 이관 완료")

    await src_engine.dispose()
    await dst_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
