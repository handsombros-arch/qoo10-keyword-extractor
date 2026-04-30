"""사장님 메인 Chrome 의 cookies → httpx Cookie jar 주입.

Chrome 종료 안 해도 됨 (Cookies SQLite 파일을 임시 폴더로 복사 후 read).
Naver 봇 감지 우회 위해 실제 사용자 세션 cookies 활용.

흐름:
  1. Chrome User Data\Local State 읽기 → DPAPI encrypted master key
  2. win32crypt.CryptUnprotectData → master key 복호화
  3. Cookies SQLite (Network/Cookies) 임시 복사 → SQL select
  4. encrypted_value (v10/v20 prefix) → AES-GCM 복호화
  5. httpx.Cookies 객체 반환

env:
  CHROME_COOKIES_PROFILE   default 'Default' (사장님 메인). 'Profile 1' 등 다른 프로필 가능
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _local_state_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data/Local State"


def _profile_dir(profile: str = "") -> Path:
    profile = profile or os.getenv("CHROME_COOKIES_PROFILE", "Default")
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data" / profile


def _get_master_key() -> Optional[bytes]:
    """Chrome Local State 에서 master key 추출 + DPAPI 복호화."""
    ls = _local_state_path()
    if not ls.exists():
        logger.warning(f"[chrome_cookies] Local State 없음: {ls}")
        return None
    try:
        data = json.loads(ls.read_text(encoding="utf-8"))
        encrypted_b64 = data["os_crypt"]["encrypted_key"]
    except Exception as e:
        logger.warning(f"[chrome_cookies] Local State 파싱 실패: {e}")
        return None

    encrypted = base64.b64decode(encrypted_b64)
    if not encrypted.startswith(b"DPAPI"):
        logger.warning("[chrome_cookies] DPAPI prefix 없음")
        return None
    encrypted = encrypted[5:]  # strip 'DPAPI'

    try:
        import win32crypt
        decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1]
        return decrypted
    except Exception as e:
        logger.warning(f"[chrome_cookies] DPAPI 복호화 실패: {e}")
        return None


def _decrypt_cookie_value(encrypted: bytes, key: bytes) -> str:
    """v10/v11/v20 cookie 값 → 평문."""
    if not encrypted:
        return ""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception:
        return ""

    if encrypted[:3] in (b"v10", b"v11"):
        nonce = encrypted[3:15]
        ciphertext = encrypted[15:]
        try:
            aes = AESGCM(key)
            return aes.decrypt(nonce, ciphertext, None).decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"[chrome_cookies] v10/11 decrypt fail: {e}")
            return ""
    if encrypted[:3] == b"v20":
        # v20 — 향후 Chrome 새 포맷 (현재 일부 환경). nonce/tag 위치 다름.
        try:
            nonce = encrypted[3:15]
            ciphertext = encrypted[15:-16]
            tag = encrypted[-16:]
            aes = AESGCM(key)
            return aes.decrypt(nonce, ciphertext + tag, None).decode("utf-8", errors="replace")
        except Exception:
            return ""
    # legacy DPAPI 포맷 (오래된 Chrome)
    try:
        import win32crypt
        return win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1].decode(
            "utf-8", errors="replace"
        )
    except Exception:
        return ""


def _safe_copy_cookies_db(src: Path, dst: Path) -> bool:
    """Cookies SQLite 임시 복사 (Chrome 떠있어도 read 가능).

    Chrome 가 잠그면 → Windows API (FILE_SHARE_READ) 로 강제 read.
    """
    try:
        shutil.copy2(src, dst)
        return True
    except PermissionError:
        # Windows 파일 잠금 우회 — ctypes 로 FILE_SHARE_READ 옵션 read
        try:
            import ctypes
            from ctypes import wintypes

            GENERIC_READ = 0x80000000
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            FILE_SHARE_DELETE = 0x00000004
            OPEN_EXISTING = 3
            FILE_ATTRIBUTE_NORMAL = 0x80
            INVALID_HANDLE = ctypes.c_void_p(-1).value

            kernel32 = ctypes.windll.kernel32
            kernel32.CreateFileW.restype = wintypes.HANDLE
            handle = kernel32.CreateFileW(
                str(src),
                GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
            )
            if handle == INVALID_HANDLE or handle == 0:
                logger.warning(f"[chrome_cookies] CreateFileW fail")
                return False

            # ReadFile 으로 통째 읽기
            file_size = src.stat().st_size
            buf = ctypes.create_string_buffer(file_size)
            bytes_read = wintypes.DWORD()
            ok = kernel32.ReadFile(handle, buf, file_size, ctypes.byref(bytes_read), None)
            kernel32.CloseHandle(handle)
            if not ok:
                return False
            with open(dst, "wb") as f:
                f.write(buf.raw[:bytes_read.value])
            return True
        except Exception as e:
            logger.warning(f"[chrome_cookies] WinAPI copy 실패: {e}")
            return False
    except Exception as e:
        logger.warning(f"[chrome_cookies] DB copy 실패: {e}")
        return False


def fetch_cookies_for_domain(
    domain_substring: str,
    profile: str = "",
) -> dict[str, str]:
    """domain 에 해당하는 cookies → {name: value} dict.

    예: 'naver.com' 으로 호출 → naver.com 및 모든 sub-도메인 cookies.
    실패 시 빈 dict.
    """
    profile_path = _profile_dir(profile)
    cookies_db = profile_path / "Network" / "Cookies"
    if not cookies_db.exists():
        # legacy 위치 fallback
        cookies_db = profile_path / "Cookies"
    if not cookies_db.exists():
        logger.warning(f"[chrome_cookies] Cookies DB 없음: {cookies_db}")
        return {}

    key = _get_master_key()
    if not key:
        return {}

    out: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as td:
        tmp_db = Path(td) / "Cookies"
        if not _safe_copy_cookies_db(cookies_db, tmp_db):
            return {}

        try:
            conn = sqlite3.connect(str(tmp_db))
            cur = conn.cursor()
            cur.execute(
                "SELECT host_key, name, encrypted_value, value FROM cookies "
                "WHERE host_key LIKE ?",
                (f"%{domain_substring}%",),
            )
            for host, name, enc_val, plain_val in cur.fetchall():
                if enc_val:
                    val = _decrypt_cookie_value(enc_val, key)
                else:
                    val = plain_val or ""
                if name and val:
                    out[name] = val
            conn.close()
        except Exception as e:
            logger.warning(f"[chrome_cookies] SQLite read 실패: {e}")
            return {}

    return out


def fetch_cookies_as_header(domain_substring: str, profile: str = "") -> str:
    """fetch → Cookie 헤더 형식 'name1=val1; name2=val2; ...'."""
    cookies = fetch_cookies_for_domain(domain_substring, profile)
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


__all__ = ["fetch_cookies_for_domain", "fetch_cookies_as_header"]
