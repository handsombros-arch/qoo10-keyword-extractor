"""텔레그램 + Slack 알림 유틸 (둘 다 동시 전송).

토큰이 없으면 콘솔 출력만 하고 silent fail (자동화 자체는 계속).
AUTOMATION_DRY_RUN=1 이면 메시지에 [DRY RUN] 프리픽스 자동 부착.

env:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  (선택)
    SLACK_WEBHOOK_URL                       (선택, Incoming Webhook URL)
    NOTIFY_CHANNELS=telegram,slack          (선택, 기본 둘 다 — 콤마구분)
"""
from __future__ import annotations

import asyncio
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


def _enabled_channels() -> set[str]:
    raw = (os.getenv("NOTIFY_CHANNELS") or "telegram,slack").strip().lower()
    return {c.strip() for c in raw.split(",") if c.strip()}


async def _send_telegram(body: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
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
                    f"[notify/telegram] {resp.status_code}: {resp.text[:300]}",
                    file=sys.stderr,
                )
                return False
            return True
    except Exception as e:
        print(f"[notify/telegram] 실패(무시): {type(e).__name__}: {e!r}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return False


async def _send_slack(body: str) -> bool:
    webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(webhook, json={"text": body})
            if resp.status_code not in (200, 204):
                print(f"[notify/slack] {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
                return False
            return True
    except Exception as e:
        print(f"[notify/slack] 실패(무시): {type(e).__name__}: {e!r}", file=sys.stderr)
        return False


async def send(text: str, level: str = "info") -> bool:
    """텔레그램 + Slack 동시 전송. 실패해도 자동화는 계속됨.

    Returns:
        True — 적어도 한 채널 성공. False — 모두 실패/미설정.
    """
    prefix = _LEVEL_PREFIX.get(level, "ℹ️")
    body = f"{prefix} {text}"
    if _is_dry_run():
        body = f"[DRY RUN] {body}"

    # 콘솔에는 항상 표시
    print(body, file=sys.stderr, flush=True)

    channels = _enabled_channels()
    tasks = []
    if "telegram" in channels:
        tasks.append(_send_telegram(body))
    if "slack" in channels:
        tasks.append(_send_slack(body))

    if not tasks:
        return False

    # 두 채널 병렬 전송 — 한 채널 실패해도 다른 채널 영향 X
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return any(r is True for r in results)
