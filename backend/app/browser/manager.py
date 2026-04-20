import asyncio
import shutil
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.browser.session import load_cookies, save_cookies
from app.config import settings


def _find_chrome_path() -> Optional[str]:
    """시스템에 설치된 Chrome 경로 찾기"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    found = shutil.which("chrome") or shutil.which("google-chrome")
    return found


class BrowserManager:
    """Playwright 브라우저 싱글톤 관리자"""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._lock = asyncio.Lock()
        self._logged_in = False
        self._last_error: Optional[str] = None

    def _is_alive(self) -> bool:
        """브라우저와 페이지가 실제로 살아있는지 확인"""
        try:
            if not self._browser or not self._browser.is_connected():
                return False
            if not self._page or self._page.is_closed():
                return False
            return True
        except Exception:
            return False

    async def initialize(self) -> None:
        """완전히 새로 브라우저를 시작. 기존 쿠키 기반 로그인 상태는 유지."""
        # 기존 리소스 정리 (단, 명시적 logout이 아니므로 로그인 플래그 유지)
        await self.close(keep_login_flag=True)

        self._playwright = await async_playwright().start()

        chrome_path = _find_chrome_path()

        launch_options = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        }

        if chrome_path:
            launch_options["executable_path"] = chrome_path

        try:
            self._browser = await self._playwright.chromium.launch(**launch_options)
            self._last_error = None
        except Exception as e:
            self._last_error = f"Chrome 실패({e}), Chromium으로 재시도"
            launch_options.pop("executable_path", None)
            self._browser = await self._playwright.chromium.launch(**launch_options)

        self._context = await self._browser.new_context(
            viewport={"width": 1600, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )

        # 저장된 쿠키 복원 — 쿠키가 있으면 낙관적으로 로그인 상태 유지
        cookies = await load_cookies(settings.COOKIES_PATH)
        if cookies:
            try:
                await self._context.add_cookies(cookies)
                # 유효한 세션 쿠키가 있으면 is_logged_in = True (실제 검증은 verify_login에서)
                if any(c.get("name", "").lower() in ("gmkt.inc.session", "jsessionid", "session_id", "sessionid") or
                       "session" in c.get("name", "").lower() for c in cookies):
                    self._logged_in = True
            except Exception:
                pass

        self._page = await self._context.new_page()

    async def verify_login(self) -> bool:
        """실제로 QSM에 접속해 로그인 페이지로 리디렉션되는지 확인. 실패 시 is_logged_in=False."""
        try:
            page = await self.get_page()
            await page.goto(settings.QSM_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(1000)
            url = page.url
            ok = "qsm.qoo10.jp" in url and "/Login" not in url and "/login" not in url
            self._logged_in = ok
            return ok
        except Exception:
            return self._logged_in

    async def get_page(self) -> Page:
        """살아있는 페이지 반환. 죽어있으면 재초기화."""
        if not self._is_alive():
            await self.initialize()
        return self._page

    async def save_session(self) -> None:
        if self._context:
            try:
                cookies = await self._context.cookies()
                await save_cookies(cookies, settings.COOKIES_PATH)
            except Exception:
                pass

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @is_logged_in.setter
    def is_logged_in(self, value: bool):
        self._logged_in = value

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    async def close(self, keep_login_flag: bool = False) -> None:
        """브라우저 리소스 정리. keep_login_flag=True면 로그인 상태 유지 (재초기화 대비)."""
        for cleanup in [
            lambda: self._page.close() if self._page and not self._page.is_closed() else None,
            lambda: self._browser.close() if self._browser else None,
            lambda: self._playwright.stop() if self._playwright else None,
        ]:
            try:
                result = cleanup()
                if result:
                    await result
            except Exception:
                pass

        self._browser = None
        self._playwright = None
        self._page = None
        self._context = None
        if not keep_login_flag:
            self._logged_in = False


browser_manager = BrowserManager()
