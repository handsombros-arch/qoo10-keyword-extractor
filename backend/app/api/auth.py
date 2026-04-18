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
    }


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
async def start_login():
    """브라우저를 열고 Qoo10 로그인 페이지로 이동 + ID/PW 자동 입력"""
    try:
        # 항상 새 크롬 창으로 시작
        await browser_manager.close()
        await browser_manager.initialize()
        page = await browser_manager.get_page()
        try:
            await page.bring_to_front()
        except Exception:
            pass

        await page.goto(settings.QSM_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        current_url = page.url

        if "qsm.qoo10.jp" in current_url and "/Login" not in current_url and "/login" not in current_url:
            browser_manager.is_logged_in = True
            await browser_manager.save_session()
            return {
                "status": "success",
                "message": "이미 로그인된 상태입니다.",
                "url": current_url,
            }

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
                "ID/PW가 입력되었습니다. 보안문자 입력 후 로그인 버튼을 누르세요."
                if autofilled
                else "크롬 창에서 로그인을 완료한 후 '로그인 완료' 버튼을 클릭하세요."
            ),
            "autofilled": autofilled,
            "url": current_url,
            "title": title,
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
