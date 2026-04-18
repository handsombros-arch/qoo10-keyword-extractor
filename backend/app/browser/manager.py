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
        """완전히 새로 브라우저를 시작"""
        # 기존 리소스 정리
        await self.close()

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

        # 저장된 쿠키 복원
        cookies = await load_cookies(settings.COOKIES_PATH)
        if cookies:
            try:
                await self._context.add_cookies(cookies)
            except Exception:
                pass

        self._page = await self._context.new_page()

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

    async def close(self) -> None:
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
        self._logged_in = False


browser_manager = BrowserManager()
