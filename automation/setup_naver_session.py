"""네이버 영구 컨텍스트 셋업 (한 번만 실행).

automation/data/naver_session/ 디렉토리에 영구 Chromium 컨텍스트를 만든다.
사용자가 그 안에서 네이버를 사람처럼 사용 (검색·스크롤·필요하면 로그인) 하면
쿠키·localStorage·신뢰 점수가 누적되어 이후 자동화가 봇 차단을 통과하기 쉬워진다.

사용:
    python automation/setup_naver_session.py

권장 행동:
    1. 창이 뜨면 네이버 검색창에 키워드 몇 개 직접 타이핑하고 검색
    2. 검색 결과에서 상품 카드 1~2개 클릭해서 상세 페이지 보기
    3. 뒤로가기 눌러서 결과 페이지로 돌아오기
    4. 스크롤 천천히
    5. (선택) 네이버 계정 로그인
    6. 다 됐으면 그냥 창 닫기 → 세션이 자동 저장됨
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

from playwright.async_api import async_playwright


_THIS_DIR = Path(__file__).resolve().parent
SESSION_DIR = _THIS_DIR / "data" / "naver_session"
SESSION_DIR.mkdir(parents=True, exist_ok=True)


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _find_chrome_path() -> str | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return shutil.which("chrome") or shutil.which("google-chrome")


async def main_async() -> int:
    chrome_path = _find_chrome_path()
    print(f"브라우저: {chrome_path or 'Playwright 번들 Chromium'}")
    print(f"영구 세션 디렉토리: {SESSION_DIR}")
    print()
    print("─" * 60)
    print("  네이버 세션 셋업")
    print("─" * 60)
    print("창이 뜨면 다음을 사람처럼 천천히 해주세요:")
    print("  1. 검색창에 키워드 2~3개 직접 입력 후 검색 (예: 커피, 비타민, 키보드)")
    print("  2. 검색 결과에서 상품 1~2개 클릭 → 상세 보기 → 뒤로가기")
    print("  3. 스크롤 천천히 (마우스 휠)")
    print("  4. (선택) 우상단에서 네이버 로그인")
    print("  5. 다 됐으면 그냥 창을 X로 닫아주세요")
    print("─" * 60)
    print()

    async with async_playwright() as p:
        launch_options = {
            "headless": False,
            "viewport": {"width": 1400, "height": 900},
            "user_agent": USER_AGENT,
            "ignore_https_errors": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        }
        if chrome_path:
            launch_options["executable_path"] = chrome_path

        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                **launch_options,
            )
        except Exception as e:
            if "executable_path" in launch_options:
                print(f"시스템 Chrome 실패({e}), Playwright 번들 Chromium 으로 재시도")
                launch_options.pop("executable_path", None)
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(SESSION_DIR),
                    **launch_options,
                )
            else:
                raise

        # 첫 페이지: 네이버 쇼핑 메인
        if context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()

        try:
            await page.goto(
                "https://shopping.naver.com/", wait_until="domcontentloaded", timeout=30000
            )
        except Exception as e:
            print(f"초기 페이지 로드 경고(무시): {e}")

        print("창이 닫힐 때까지 대기 중... (사용자가 X 버튼 누를 때까지)")
        # 창 닫힘 감지 — 모든 페이지/컨텍스트가 닫힐 때까지 대기
        closed_event = asyncio.Event()

        def _on_close():
            closed_event.set()

        context.on("close", lambda *_: _on_close())

        # 모든 페이지 close 도 감지
        async def _watch():
            while not closed_event.is_set():
                if not context.pages:
                    closed_event.set()
                    break
                await asyncio.sleep(2)

        await _watch()

        try:
            await context.close()
        except Exception:
            pass

    print()
    print("✅ 네이버 세션 저장 완료. 이후 자동화에서 이 세션을 재사용합니다.")
    print(f"   세션 디렉토리: {SESSION_DIR}")
    print()
    print("다음 단계: python automation/diagnose_naver_session.py")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
