"""텔레그램 알림 유틸.

토큰/chat_id가 없으면 콘솔 출력만 하고 silent fail (자동화 자체는 계속).
환경변수 AUTOMATION_DRY_RUN=1 이면 메시지에 [DRY RUN] 프리픽스 자동 부착.
"""
from __future__ import annotations

import os
import sys
import traceback

import httpx


_LEVEL_PREFIX = {
    "info": "▶️",
    "ok": "✅",
    "warn": "⚠️",
    "auth": "🔐",
    "error": "❌",
}


def _is_dry_run() -> bool:
    return os.getenv("AUTOMATION_DRY_RUN", "0") == "1"


async def send(text: str, level: str = "info") -> bool:
    """텔레그램 메시지 전송. 실패해도 자동화는 계속됨.

    Returns:
        True 전송 성공, False 토큰 없음/실패.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    prefix = _LEVEL_PREFIX.get(level, "ℹ️")
    body = f"{prefix} {text}"
    if _is_dry_run():
        body = f"[DRY RUN] {body}"

    # 콘솔에는 항상 표시
    print(body, file=sys.stderr, flush=True)

    if not token or not chat_id:
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": body,
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code != 200:
                print(
                    f"[notify] 텔레그램 응답 {resp.status_code}: {resp.text[:500]}",
                    file=sys.stderr,
                )
                return False
            return True
    except Exception as e:
        print(
            f"[notify] 텔레그램 전송 실패(무시): "
            f"{type(e).__name__}: {e!r}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return False
