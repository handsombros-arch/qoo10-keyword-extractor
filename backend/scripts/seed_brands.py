"""brands 테이블 초기 시드 (1회용).

backend/app/data/brands/whitelist.json 의 50개 K-뷰티/식품 브랜드를
Supabase brands 테이블에 INSERT. 이미 존재하는 kr 은 SKIP.

사용:
    cd backend
    python -m scripts.seed_brands

재실행 안전 (UNIQUE kr 충돌 시 그냥 건너뜀).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Windows + asyncpg + SSL 조합에서 ProactorEventLoop 종료 시 SSL transport
# 정리 실패로 traceback 이 출력되는 알려진 이슈. SelectorEventLoop 로 회피.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db.connection import async_session, engine  # noqa: E402
from app.db.models import Base, Brand  # noqa: E402

_WHITELIST = _BACKEND / "app" / "data" / "brands" / "whitelist.json"


async def main() -> int:
    if not _WHITELIST.exists():
        print(f"[ERR] 시드 파일 없음: {_WHITELIST}")
        return 1

    seeds = json.loads(_WHITELIST.read_text(encoding="utf-8"))
    print(f"[seed_brands] 시드 {len(seeds)}개 로드")

    # 테이블이 아직 없을 수 있으니 보장 (main.py 가 평소엔 만들어주지만 단독 실행 대비)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    inserted = skipped = 0
    async with async_session() as session:
        existing = {
            row.kr for row in (await session.execute(select(Brand.kr))).scalars().all()
        }
        for item in seeds:
            kr = (item.get("kr") or "").strip()
            if not kr:
                continue
            if kr in existing:
                skipped += 1
                continue
            session.add(Brand(
                kr=kr,
                jp=(item.get("jp") or "").strip(),
                en=(item.get("en") or "").strip(),
                source="seed",
                confidence=1.0,
            ))
            existing.add(kr)
            inserted += 1
        await session.commit()

    print(f"[seed_brands] 신규 {inserted}개, 스킵(이미존재) {skipped}개")

    # 종료 전 connection pool 명시적 정리 (SSL transport 깨끗하게 닫기)
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
