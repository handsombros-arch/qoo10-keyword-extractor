"""sync wrapper 공통 헬퍼.

CLI / 단발 검증용. asyncio.run() 을 직접 쓰는 대신 이 함수를 통하면:
    1) Windows 에서 SelectorEventLoop 사용 (asyncpg + SSL 호환)
    2) 종료 전 SQLAlchemy engine.dispose() 로 connection pool 정리

Windows + ProactorEventLoop + asyncpg + SSL 조합에서 종료 시
"Fatal error on SSL transport / Event loop is closed" traceback 이 출력되는
알려진 이슈를 회피한다.

정책 변경은 호출 시점에만 하고 호출 종료 후 원복한다 (Playwright 등
ProactorEventLoop 가 필요한 다른 코드 경로에 영향 없도록).
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Awaitable


async def _with_dispose(coro: Awaitable[Any]) -> Any:
    try:
        return await coro
    finally:
        # asyncpg connection pool 정리. import 시점에 의존하지 않도록 lazy import.
        try:
            from app.db.connection import engine
            await engine.dispose()
        except Exception:
            pass


def run_sync(coro: Awaitable[Any]) -> Any:
    """Windows 정책 임시 전환 + dispose 보장 후 코루틴 실행."""
    if sys.platform != "win32":
        return asyncio.run(_with_dispose(coro))

    original = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(_with_dispose(coro))
    finally:
        asyncio.set_event_loop_policy(original)


__all__ = ["run_sync"]
