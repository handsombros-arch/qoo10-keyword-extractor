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
        # Windows
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
        # macOS (맥북 24h 서버용)
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        # Linux
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    found = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
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
        """브라우저와 페이지가 실제로 살아있는지 확인 (persistent context 대응)"""
        try:
            # persistent context 면 self._browser 가 None 일 수 있음 → context 직접 확인
            if not self._context:
                return False
            if not self._page or self._page.is_closed():
                return False
            # context.pages 체크로 살아있는지 검증
            try:
                _ = self._context.pages
                return True
            except Exception:
                return False
        except Exception:
            return False

    async def initialize(self) -> None:
        """완전히 새로 브라우저를 시작.

        CCCC-1: launch_persistent_context 사용 → user_data_dir 영구 보존
                → cookies + storage + indexedDB + sessionStorage 모두 자동
                → 사장님 1회 로그인 → 영구 자동 로그인
        """
        # 기존 리소스 정리 (단, 명시적 logout이 아니므로 로그인 플래그 유지)
        await self.close(keep_login_flag=True)

        self._playwright = await async_playwright().start()

        chrome_path = _find_chrome_path()

        # CCCC-1: 영구 user-data-dir (data/qoo10-browser-profile)
        user_data_dir = Path(settings.COOKIES_PATH).parent / "qoo10-browser-profile"
        user_data_dir.mkdir(parents=True, exist_ok=True)

        launch_options = {
            "user_data_dir": str(user_data_dir),
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            "viewport": {"width": 1600, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            "ignore_https_errors": True,
            "locale": "ja-JP",
        }

        if chrome_path:
            launch_options["executable_path"] = chrome_path

        try:
            # persistent context — browser 와 context 가 합쳐짐
            self._context = await self._playwright.chromium.launch_persistent_context(**launch_options)
            self._browser = self._context.browser  # 일부 자리에서 참조 (보통 None for persistent)
            self._last_error = None
        except Exception as e:
            self._last_error = f"Chrome 실패({e}), Chromium으로 재시도"
            launch_options.pop("executable_path", None)
            self._context = await self._playwright.chromium.launch_persistent_context(**launch_options)
            self._browser = self._context.browser

        # 추가 cookies 복원 (다른 PC 동기화용 — settings.COOKIES_PATH)
        # persistent profile 에 이미 있을 가능성 높지만 cross-PC sync 용도
        cookies = await load_cookies(settings.COOKIES_PATH)
        if cookies:
            try:
                await self._context.add_cookies(cookies)
                if any(c.get("name", "").lower() in ("gmkt.inc.session", "jsessionid", "session_id", "sessionid") or
                       "session" in c.get("name", "").lower() for c in cookies):
                    self._logged_in = True
            except Exception:
                pass

        # persistent context 는 first page 자동 생성됨
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

    async def verify_login(self) -> bool:
        """실제로 QSM에 접속해 로그인 페이지로 리디렉션되는지 확인. 실패 시 is_logged_in=False.

        K (5/3): 성공 시 save_session() 즉시 호출 — 사장님이 수동으로 captcha 풀어
        로그인 직후 verify 가 호출되면 그 시점 cookies 가 영속 파일에 즉시 백업됨.
        """
        try:
            page = await self.get_page()
            await page.goto(settings.QSM_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(1000)
            url = page.url
            ok = "qsm.qoo10.jp" in url and "/Login" not in url and "/login" not in url
            self._logged_in = ok
            if ok:
                try:
                    await self.save_session()
                except Exception:
                    pass
            return ok
        except Exception:
            return self._logged_in

    async def get_page(self) -> Page:
        """살아있는 페이지 반환. 죽어있으면 재초기화."""
        if not self._is_alive():
            await self.initialize()
        return self._page

    async def new_page(self) -> Page:
        """별도 작업용 새 탭 (예: Papago 번역). 호출측이 close() 책임.
        QSM 메인 페이지를 건드리지 않음."""
        if not self._is_alive():
            await self.initialize()
        return await self._context.new_page()

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
        """브라우저 리소스 정리. keep_login_flag=True면 로그인 상태 유지 (재초기화 대비).

        CCCC-1: persistent context 면 context.close() 가 user_data_dir 의 변경 사항 flush.
        """
        for cleanup in [
            lambda: self._page.close() if self._page and not self._page.is_closed() else None,
            # persistent context — context.close() 만 (browser 별도 X)
            lambda: self._context.close() if self._context else None,
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
