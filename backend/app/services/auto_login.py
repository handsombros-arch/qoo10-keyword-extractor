"""서버 시작 시 자동 로그인.

start.pyw 더블클릭 한 번으로 큐텐 로그인까지 완료되도록 백그라운드에서 시도.
- 쿠키 유효하면 → 그냥 is_logged_in=True
- 쿠키 만료 + 저장 자격정보 있으면 → 크롬 자동 열고 ID/PW fill + 로그인 버튼 클릭 시도
- 캡차 등으로 실패하면 창만 열어두고 사용자 수동 완료 대기
"""
import asyncio
import json
import traceback
from pathlib import Path

from app.browser.manager import browser_manager
from app.config import settings


async def _wait_for_server_ready(port: int = 8000, timeout: int = 15) -> bool:
    """uvicorn이 완전히 뜰 때까지 대기."""
    import urllib.request
    for _ in range(timeout):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/auth/status", timeout=1)
            return True
        except Exception:
            await asyncio.sleep(1)
    return False


def _load_credentials() -> dict:
    path = settings.SESSION_DIR / "credentials.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


async def auto_login_on_startup():
    """서버 시작 수 초 후 백그라운드에서 자동 로그인 시도."""
    # 1) 서버 부트 완료 대기
    await asyncio.sleep(3)

    try:
        # 2) 쿠키 파일 없으면 자동 로그인 시도 자체를 스킵
        if not settings.COOKIES_PATH.exists():
            creds = _load_credentials()
            if not (creds.get("user_id") and creds.get("password")):
                print("[auto_login] 쿠키·자격정보 없음. 수동 로그인 필요.")
                return

        # 3) 브라우저 초기화 (쿠키 자동 복원)
        if not browser_manager._is_alive():
            await browser_manager.initialize()

        page = await browser_manager.get_page()
        try:
            await page.bring_to_front()
        except Exception:
            pass

        await page.goto(settings.QSM_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        url = page.url
        # 4) 쿠키로 이미 로그인됨
        if "qsm.qoo10.jp" in url and "/Login" not in url and "/login" not in url:
            browser_manager.is_logged_in = True
            await browser_manager.save_session()
            print(f"[auto_login] 쿠키 복원 성공: {url}")
            return

        # 5) 로그인 페이지 → 저장 자격정보로 자동 fill + 로그인 시도
        creds = _load_credentials()
        if not (creds.get("user_id") and creds.get("password")):
            print("[auto_login] 로그인 페이지로 리디렉션. 자격정보 없어서 중단 (사용자 수동 입력 필요).")
            return

        try:
            id_input = await page.query_selector("#txtLoginID")
            pw_input = await page.query_selector("#txtLoginPwd")
            if id_input and pw_input:
                await id_input.fill("")
                await id_input.fill(creds["user_id"])
                await pw_input.fill("")
                await pw_input.fill(creds["password"])
                await page.wait_for_timeout(500)

                # 로그인 버튼 클릭 시도 (여러 셀렉터)
                login_btn = None
                for sel in [
                    "#btnLogin",
                    "button[type='submit']",
                    ".btn_login",
                    "a.btn_login",
                    "input[type='submit']",
                ]:
                    login_btn = await page.query_selector(sel)
                    if login_btn:
                        break
                if login_btn:
                    await login_btn.click()
                    # 캡차 없으면 성공, 있으면 로그인 페이지에 남음
                    await page.wait_for_timeout(4000)

                    url2 = page.url
                    if "qsm.qoo10.jp" in url2 and "/Login" not in url2 and "/login" not in url2:
                        browser_manager.is_logged_in = True
                        await browser_manager.save_session()
                        print(f"[auto_login] 자동 로그인 성공: {url2}")
                        return
                    else:
                        print(f"[auto_login] 자동 로그인 실패 (캡차 등). 사용자 수동 완료 대기: {url2}")
                        return
                else:
                    print("[auto_login] 로그인 버튼 못 찾음. 사용자 수동 완료 대기.")
            else:
                print("[auto_login] 로그인 인풋 없음.")
        except Exception as e:
            print(f"[auto_login] 자동 fill/클릭 실패: {e}")

    except Exception as e:
        traceback.print_exc()
        print(f"[auto_login] 전체 실패: {e}")
