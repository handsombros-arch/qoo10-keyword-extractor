import asyncio

from app.browser.manager import BrowserManager
from app.config import settings
from app.scrapers.base import BaseScraper


class LoginScraper(BaseScraper):
    """M01: Qoo10 QSM 로그인"""

    async def run(self, **params) -> dict:
        page = await self.browser.get_page()

        # QSM 로그인 페이지로 이동
        await page.goto(settings.QSM_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        return {"status": "login_page_opened"}

    async def check_login_status(self) -> bool:
        """로그인 완료 여부 확인"""
        page = await self.browser.get_page()

        try:
            current_url = page.url
            # 로그인 페이지에 있으면 아직 로그인 안 됨
            if "/Login" in current_url or "/login" in current_url:
                return False

            # QSM 메인에서 로그아웃 링크가 있는지 확인
            logout_link = await page.query_selector('a[href*="Logout"], a[href*="logout"]')
            if logout_link:
                return True

            # content 영역에 사용자 정보가 표시되는지 확인
            user_info = await page.query_selector('#header .user-info, #header .gnb_login')
            if user_info:
                return True

            # URL이 QSM 메인이면 로그인된 것으로 간주
            if "qsm.qoo10.jp" in current_url and "/Login" not in current_url:
                return True

        except Exception:
            pass

        return False

    async def wait_for_login(self, timeout: int = 300) -> bool:
        """사용자가 로그인할 때까지 대기 (최대 timeout초)"""
        for _ in range(timeout // 2):
            if await self.check_login_status():
                await self.browser.save_session()
                self.browser.is_logged_in = True
                return True
            await asyncio.sleep(2)
        return False

    async def restore_session(self) -> bool:
        """저장된 쿠키로 세션 복원 시도"""
        page = await self.browser.get_page()
        await page.goto(settings.QSM_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        if await self.check_login_status():
            self.browser.is_logged_in = True
            return True

        return False
