"""Naver 세션 헬스체크 — naver-browser-profile 쿠키 검사.

야간 자동화 시작 전 + 사장님 수동 호출용.
실제 fetch 안 하고 디스크 쿠키만 검사 → 빠르고 부담 없음.

만료 감지 시: 텔레그램/슬랙 알림 + 자동화 skip.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Chrome WebKit time → Unix epoch
# WebKit: microseconds since 1601-01-01 UTC
# Unix:   seconds since 1970-01-01 UTC
# 차이: 11644473600 초
_WEBKIT_EPOCH_DELTA_US = 11644473600_000_000


def _webkit_to_dt(webkit_us: int) -> datetime | None:
    """Chrome cookies expires_utc → datetime. 0 / 음수 = session cookie."""
    if not webkit_us or webkit_us <= 0:
        return None
    unix_us = webkit_us - _WEBKIT_EPOCH_DELTA_US
    if unix_us <= 0:
        return None
    return datetime.fromtimestamp(unix_us / 1_000_000, tz=timezone.utc)


def _profile_cookies_db() -> Path:
    """naver-browser-profile/Default/Network/Cookies SQLite 경로."""
    return (
        Path(__file__).resolve().parent.parent.parent
        / "data" / "naver-browser-profile" / "Default" / "Network" / "Cookies"
    )


def check_naver_session() -> dict:
    """디스크 쿠키 검사. 네트워크 호출 없음 (~50ms).

    returns:
      {
        "alive": bool,
        "details": "...",
        "cookies": {NID_AUT: {persistent, expires_iso, expired}, ...},
      }
    """
    db = _profile_cookies_db()
    if not db.exists():
        return {
            "alive": False,
            "details": "쿠키 DB 없음 — naver-browser-profile 한 번도 사용 안 됨. open_naver_login_chrome.bat 실행 필요.",
            "cookies": {},
        }

    # Chrome 이 lock 잡고 있을 수 있어 임시 복사 (read-only)
    tmp = Path(tempfile.mkdtemp()) / "cookies.sqlite"
    try:
        shutil.copy2(db, tmp)
    except Exception as e:
        return {
            "alive": False,
            "details": f"쿠키 DB 복사 실패: {e}",
            "cookies": {},
        }

    required = {"NID_AUT", "NID_SES"}
    optional = {"nid_inf", "NID_JKL"}
    found: dict[str, dict] = {}

    try:
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        cur = conn.execute(
            "SELECT name, expires_utc, is_persistent, host_key "
            "FROM cookies WHERE host_key LIKE '%naver%' "
            f"AND name IN ({','.join('?'*len(required|optional))})",
            tuple(required | optional),
        )
        for name, exp, persistent, host in cur.fetchall():
            dt = _webkit_to_dt(exp)
            found[name] = {
                "persistent": bool(persistent),
                "host": host,
                "expires_iso": dt.isoformat() if dt else None,
                "expired": (dt is not None and dt < datetime.now(timezone.utc)),
                "session_cookie": dt is None,
            }
        conn.close()
    except Exception as e:
        return {"alive": False, "details": f"쿠키 DB 읽기 실패: {e}", "cookies": {}}
    finally:
        try:
            tmp.unlink(missing_ok=True)
            tmp.parent.rmdir()
        except Exception:
            pass

    missing = required - set(found)
    if missing:
        return {
            "alive": False,
            "details": f"필수 쿠키 누락: {sorted(missing)}. 재로그인 필요.",
            "cookies": found,
        }

    expired = [n for n in required if found[n].get("expired")]
    if expired:
        return {
            "alive": False,
            "details": f"쿠키 만료: {expired}. 재로그인 필요.",
            "cookies": found,
        }

    session_only = [n for n in required if found[n].get("session_cookie")]
    if session_only:
        return {
            "alive": False,
            "details": (
                f"세션 쿠키임 ({session_only}) — '로그인 유지' 미체크 상태. "
                "재로그인 시 '로그인 유지' 체크 필수."
            ),
            "cookies": found,
        }

    # OK
    earliest = min(
        (datetime.fromisoformat(found[n]["expires_iso"]) for n in required),
        default=None,
    )
    days_left: int | None = None
    days_left_msg = ""
    if earliest:
        days_left = (earliest - datetime.now(timezone.utc)).days
        days_left_msg = f" (만료까지 {days_left}일)"
    return {
        "alive": True,
        "details": f"NID_AUT/NID_SES 정상{days_left_msg}",
        "days_left": days_left,
        "cookies": found,
    }


__all__ = ["check_naver_session"]
