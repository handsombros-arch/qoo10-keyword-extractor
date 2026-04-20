import json
import traceback
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.browser.manager import browser_manager
from app.config import settings
from app.scrapers.m01_login import LoginScraper
from app.services.task_manager import task_manager

router = APIRouter(prefix="/api/auth", tags=["auth"])

CREDENTIALS_PATH: Path = settings.SESSION_DIR / "credentials.json"


class Credentials(BaseModel):
    user_id: str = ""
    password: str = ""


def _load_credentials() -> Credentials:
    if CREDENTIALS_PATH.exists():
        try:
            data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
            return Credentials(**data)
        except Exception:
            pass
    return Credentials()


def _save_credentials(creds: Credentials) -> None:
    CREDENTIALS_PATH.write_text(
        json.dumps(creds.model_dump(), ensure_ascii=False),
        encoding="utf-8",
    )


def _get_login_scraper() -> LoginScraper:
    return LoginScraper(browser_manager, task_manager)


@router.get("/status")
async def get_login_status():
    return {
        "logged_in": browser_manager.is_logged_in,
        "browser_active": browser_manager._browser is not None,
        "last_error": browser_manager.last_error,
        "has_cookies": settings.COOKIES_PATH.exists(),
    }


@router.post("/verify")
async def verify_login():
    """실제 QSM 접속하여 로그인 여부 재검증."""
    ok = await browser_manager.verify_login()
    return {"logged_in": ok}


@router.get("/credentials")
async def get_credentials():
    creds = _load_credentials()
    return {
        "user_id": creds.user_id,
        "has_password": bool(creds.password),
    }


@router.post("/credentials")
async def set_credentials(creds: Credentials):
    _save_credentials(creds)
    return {"status": "saved"}


@router.delete("/credentials")
async def delete_credentials():
    if CREDENTIALS_PATH.exists():
        CREDENTIALS_PATH.unlink()
    return {"status": "deleted"}


@router.post("/login")
async def start_login(force_new: bool = False):
    """큐텐 로그인.

    기본: 살아있는 브라우저·탭을 재사용하고 저장된 쿠키로 QSM 재진입.
    force_new=True: 브라우저를 완전히 닫고 새로 시작 (문제 발생 시만).
    """
    try:
        if force_new:
            # 명시 요청 시만 기존 브라우저 완전 종료 후 재시작
            await browser_manager.close()
            await browser_manager.initialize()
        elif not browser_manager._is_alive():
            # 죽어있으면 초기화 (쿠키는 자동 복원)
            await browser_manager.initialize()
        # 살아있으면 그대로 재사용 → 기존 탭에서 navigate

        page = await browser_manager.get_page()
        try:
            await page.bring_to_front()
        except Exception:
            pass

        await page.goto(settings.QSM_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        current_url = page.url

        # 쿠키 유효 → QSM 본 페이지 접속 완료
        if "qsm.qoo10.jp" in current_url and "/Login" not in current_url and "/login" not in current_url:
            browser_manager.is_logged_in = True
            await browser_manager.save_session()
            return {
                "status": "success",
                "message": "저장된 쿠키로 로그인 완료.",
                "url": current_url,
                "reused_browser": not force_new,
            }

        # 로그인 페이지로 리디렉션됨 → 저장된 ID/PW 자동 입력
        creds = _load_credentials()
        autofilled = False
        if creds.user_id or creds.password:
            try:
                id_input = await page.query_selector("#txtLoginID")
                pw_input = await page.query_selector("#txtLoginPwd")
                if id_input and creds.user_id:
                    await id_input.fill("")
                    await id_input.fill(creds.user_id)
                if pw_input and creds.password:
                    await pw_input.fill("")
                    await pw_input.fill(creds.password)
                autofilled = bool(id_input and pw_input)
            except Exception:
                pass

        title = await page.title()
        return {
            "status": "login_page_opened",
            "message": (
                "ID/PW가 자동 입력되었습니다. 보안문자 확인 후 로그인 버튼을 누르세요."
                if autofilled
                else "크롬 창에서 로그인을 완료한 후 '로그인 완료' 버튼을 클릭하세요. "
                     "자격정보를 /auth/credentials에 저장하면 자동 입력됩니다."
            ),
            "autofilled": autofilled,
            "url": current_url,
            "title": title,
            "reused_browser": not force_new,
        }

    except Exception as e:
        error_detail = traceback.format_exc()
        return {
            "status": "error",
            "message": f"브라우저 열기 실패: {str(e)}",
            "detail": error_detail,
        }


@router.post("/confirm")
async def confirm_login():
    """사용자가 로그인 완료 후 확인 버튼을 누르면 호출"""
    try:
        page = await browser_manager.get_page()
        current_url = page.url

        if "qsm.qoo10.jp" in current_url and "/Login" not in current_url and "/login" not in current_url:
            browser_manager.is_logged_in = True
            await browser_manager.save_session()
            return {"status": "success", "message": "로그인 완료", "url": current_url}

        return {
            "status": "pending",
            "message": "아직 로그인이 완료되지 않았습니다. 크롬 창에서 로그인하세요.",
            "url": current_url,
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/logout")
async def logout():
    await browser_manager.close()
    return {"status": "logged_out"}
