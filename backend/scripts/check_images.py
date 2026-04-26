"""DB에 저장된 qoo10_products 이미지 URL 샘플 확인."""
import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select
sys.path.insert(0, "C:/Users/Admin/qoo10-keyword-extractor/backend")
from app.db.connection import async_session
from app.db.models import Qoo10Product


async def main():
    async with async_session() as s:
        stmt = select(Qoo10Product).order_by(Qoo10Product.id.desc()).limit(10)
        rows = (await s.execute(stmt)).scalars().all()
        print(f"qoo10_products 최근 {len(rows)}건")
        for r in rows:
            img = r.cover_image_url or ""
            url = r.product_url or ""
            print(f"  kw={r.search_keyword!r:<30} name={(r.product_name or '')[:30]!r}")
            print(f"    img={img[:100]!r}")
            print(f"    url={url[:80]!r}")

asyncio.run(main())
