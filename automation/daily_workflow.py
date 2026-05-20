"""야간 자동화 워크플로우.

19시쯤 한 번 실행하면:
  1) 백엔드 헬스체크
  2) 로그인 상태 확인 (캡차/쿠키 만료면 텔레그램으로 알리고 중단)
  3) /api/keywords/trend (전체 카테고리, 비딩 포함) 수집 + 완료 대기
  4) /api/keywords/auto-filter 로 후보 키워드 추출
  5) 후보별 /api/recommendations/collect (큐텐+쿠팡+네이버) 일괄 + 완료 대기
  6) /api/recommend/auto-build 로 마진까지 계산해 user_data 에 저장

알림은 핵심만 (시작/필터0건/CAPTCHA/에러/완료) 5건 이내.
한 단계 실패 시 1회 재시도, 그래도 실패면 텔레그램 알림과 함께 종료.

사용:
    python automation/daily_workflow.py             # 실제 실행
    python automation/daily_workflow.py --dry-run   # POST 모킹 (GET은 실제)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx
from dotenv import load_dotenv


# ─── 경로 / 환경 ───────────────────────────────────────

_THIS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
LOG_DIR = _ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# automation/.env 우선, backend/.env 보충 (NAVER_CLIENT_ID 같은 backend 측 키 공유)
load_dotenv(_THIS_DIR / ".env")
load_dotenv(_ROOT_DIR / "backend" / ".env", override=False)

# notify.py 와 같은 디렉토리에서 import
sys.path.insert(0, str(_THIS_DIR))
import notify  # noqa: E402


def _env(key: str, default: str) -> str:
    return os.getenv(key, default).strip() or default


BACKEND = _env("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")
POLL_INTERVAL = int(_env("TASK_POLL_INTERVAL_SEC", "10"))
TASK_TIMEOUT = int(_env("TASK_TIMEOUT_SEC", "14400"))

FILTER_COMPETITION_MAX = float(_env("AUTO_FILTER_COMPETITION_MAX", "0.5"))
FILTER_KR_RATIO_MIN = float(_env("AUTO_FILTER_KR_RATIO_MIN", "0.3"))
FILTER_VOLUME_MIN = int(_env("AUTO_FILTER_VOLUME_MIN", "100"))
PRODUCTS_PER_KEYWORD = int(_env("PRODUCTS_PER_KEYWORD", "5"))
# 검수 페이지 (/review) 가 마진 음수 케이스도 보여주려면 음수.
# 기본 -1.0 — 100% 손실까지 통과 (사장님이 검수 페이지에서 판매가 조정해 시도).
# 시트 빌드 단계에서 한 번 더 마진 임계값 검증 (RecommendProductsPage).
MIN_MARGIN_RATE = float(_env("MIN_MARGIN_RATE", "-1.0"))

# LLM 카테고리 분류 토글 (1=ON, 0=OFF). best-effort — 실패해도 다음 단계 진행.
ENABLE_LLM_CATEGORY = _env("ENABLE_LLM_CATEGORY", "1") == "1"

# set_count 추출 토글 (1=ON, 0=OFF)
ENABLE_SET_COUNT_EXTRACTION = _env("ENABLE_SET_COUNT_EXTRACTION", "1") == "1"

# 한국 상품 이미지 다운로드+비전 토글 (1=ON, 0=OFF)
# DDD-1: 모든 SKU cover 다운 폐기. auto-build 후보만 STEP 6.7 에서 keyword 폴더로.
ENABLE_DOMESTIC_IMAGES = _env("ENABLE_DOMESTIC_IMAGES", "0") == "1"
ENABLE_CANDIDATE_IMAGES = _env("ENABLE_CANDIDATE_IMAGES", "1") == "1"

# Phase 1-D 브랜드 확장 + 매칭 토글 (1=ON, 0=OFF). R-3 통합.
ENABLE_BRAND_EXPAND = _env("ENABLE_BRAND_EXPAND", "1") == "1"
BRAND_EXPAND_TOP_N = int(_env("BRAND_EXPAND_TOP_N", "10"))
ENABLE_EXPANDED_SEARCH = _env("ENABLE_EXPANDED_SEARCH", "1") == "1"
EXPANDED_SEARCH_MAX_RESULTS = int(_env("EXPANDED_SEARCH_MAX_RESULTS", "30"))
ENABLE_MATCH_IMAGES = _env("ENABLE_MATCH_IMAGES", "1") == "1"
# 4/28 야간 4시간 타임아웃 → top_n 3 → 2 (쌍 33% 감소, 시간 ~67%)
MATCH_IMAGES_TOP_N = int(_env("MATCH_IMAGES_TOP_N", "2"))

# set_count 비전 검증 토글 + 마진 임계값 (5단계)
ENABLE_SET_COUNT_VERIFY = _env("ENABLE_SET_COUNT_VERIFY", "1") == "1"
SET_COUNT_VERIFY_MIN_MARGIN = float(_env("SET_COUNT_VERIFY_MIN_MARGIN", "2.0"))

# Phase 4-B 큐텐 SEO 콘텐츠 자동 생성 (title_jp/tags/option_name/marketing_points)
ENABLE_QOO10_CONTENT = _env("ENABLE_QOO10_CONTENT", "1") == "1"

# FFFF-1 — JP 상세 카피 자동 생성 (qoo10-jp-detail-master.md 가이드 + 한글 번역)
# 사장님 결정: 기능만 만들고 자동화 반영 X (ENABLE_JP_DETAIL=0). 사장님이 수동 trigger 또는 UI 버튼(DDDD-1) 사용.
ENABLE_JP_DETAIL = _env("ENABLE_JP_DETAIL", "0") == "1"

# HHH-1 — 매칭 image_score 낮을 때 alt 키워드 의역 → 재검색 → 재매칭
ENABLE_MATCH_RETRY = _env("ENABLE_MATCH_RETRY", "1") == "1"

# KKK-1 — 자동 학습 (사장님 swap 기반 preferred kw 주입 + quality auto-tune)
ENABLE_AUTO_LEARNING = _env("ENABLE_AUTO_LEARNING", "1") == "1"

# R-5 (2026-05-01) — STEP 4.5 M05 연관/유사 키워드 → expanded_keywords 보강.
# 큐텐 트렌드 페이지 인기도 누적 → 매일 같은 670 키워드 → STEP 4 통과 33개 거의 고정.
# 자동 필터 통과 33개 대상으로 M05 호출 → 키워드당 유사 ~5 + 연관 ~10 = ~500 신규 후보 발굴.
ENABLE_RELATED_KEYWORDS = _env("ENABLE_RELATED_KEYWORDS", "1") == "1"
RELATED_KEYWORDS_MAX_PER_PARENT = int(_env("RELATED_KEYWORDS_MAX_PER_PARENT", "15"))

# C (2026-05-03) — STEP 4.7 야간 URL 일괄 재생성. 시트의 "URL 있고 데이터 미수집" 행
# 자동 처리. Naver=확장 (메인 Chrome 켜져있어야), Coupang=백엔드 Scrapling.
# keyword_only / full 둘 다에서 동작 (모드 무관 — 시트 따로 흐름).
ENABLE_URL_BATCH_REGENERATE = _env("ENABLE_URL_BATCH_REGENERATE", "1") == "1"
URL_BATCH_LIMIT = int(_env("URL_BATCH_LIMIT", "30"))
URL_BATCH_INCLUDE_JP_DETAIL = _env("URL_BATCH_INCLUDE_JP_DETAIL", "0") == "1"

# U (2026-05-03) — STEP 4.8 샵 벤치마크 자동 동기화. 등록된 샵들에서 fetch + 신규 상품 표시.
ENABLE_SHOP_BENCHMARK_SYNC = _env("ENABLE_SHOP_BENCHMARK_SYNC", "1") == "1"
SHOP_BENCHMARK_LIMIT = int(_env("SHOP_BENCHMARK_LIMIT", "50"))
SHOP_BENCHMARK_SORT = _env("SHOP_BENCHMARK_SORT", "review")

# R-6 (2026-05-01) — 자동화 범위 제어. 사장님 결정: 매칭/이미지/auto-build 흐름 불안정 → 홀드.
# 키워드 RD (수집 + 분류 + 필터 + M05 다양성) 까지만 야간 자동화. 이후 단계는 수동 진행.
#   - "keyword_only" (기본): STEP 1~4.5 (트렌드 수집 → 분류 → 필터 → M05) 까지만 실행
#   - "full":               기존 전체 파이프라인 (STEP 5+ 포함, 레거시)
# 시트 등록은 수동 — 사장님이 KeywordPage / ReviewPage 에서 [시트로 보내기].
# URL 기반 이미지+SEO 재생성은 그대로 유지 (POST /api/products/regenerate-content-from-url).
AUTOMATION_MODE = _env("AUTOMATION_MODE", "keyword_only").lower()

# 자동 필터 카테고리 화이트리스트 (콤마구분). 비어있으면 UserData 우선 → 그것도 없으면 모두 통과.
AUTO_FILTER_CATEGORIES_ENV = _env("AUTO_FILTER_CATEGORIES", "")


DRY_RUN = False
TARGET_DATE_OVERRIDE: Optional[date] = None
log: logging.Logger = logging.getLogger("automation")


# ─── 예외 ──────────────────────────────────────────────

class StepFailed(Exception):
    """일반 단계 실패. 1회 재시도 후에도 실패하면 텔레그램 알림 후 종료."""


class CaptchaRequired(Exception):
    """캡차 또는 로그인 만료. 자동 진행 불가, 사용자 수동 처리 필요."""


# ─── 로깅 셋업 ─────────────────────────────────────────

def setup_logging(date_str: str) -> None:
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

    fh = logging.FileHandler(LOG_DIR / f"automation_{date_str}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)


# ─── HTTP 헬퍼 ─────────────────────────────────────────

async def _get(client: httpx.AsyncClient, path: str, **kwargs) -> dict:
    """GET 호출 — dry-run에서도 항상 실제 호출 (사용자 명세)."""
    url = f"{BACKEND}{path}"
    log.info(f"GET {url}")
    resp = await client.get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()


async def _post(client: httpx.AsyncClient, path: str, json_body: Optional[dict] = None) -> dict:
    """POST 호출 — dry-run 모드에서는 모킹된 응답만 반환."""
    url = f"{BACKEND}{path}"
    if DRY_RUN:
        log.info(f"[DRY RUN] would call POST {url} with {json_body}")
        # 가짜 응답 — wait_task 가 즉시 통과하도록 task_id="DRYRUN"
        return {
            "status": "dry-run",
            "task_id": "DRYRUN",
            "master_task_id": "DRYRUN",
            "message": "dry-run mock",
        }
    log.info(f"POST {url} body={json_body}")
    resp = await client.post(url, json=json_body or {}, timeout=httpx.Timeout(60.0))
    resp.raise_for_status()
    return resp.json()


async def with_retry(coro_factory: Callable[[], Awaitable[Any]], label: str) -> Any:
    """1회 재시도 후 실패하면 StepFailed 발생.

    Watchdog (1단계 R-4): 첫 실패가 ConnectError 류면 백엔드 점검 + 재시작 시도.
    """
    for attempt in (1, 2):
        try:
            return await coro_factory()
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as e:
            log.warning(f"[{label}] 연결 오류 시도 {attempt}/2: {e}")
            if attempt == 1:
                # 첫 연결 오류 — 백엔드 점검 + 재시작
                async with httpx.AsyncClient() as ping_client:
                    if not await _backend_alive(ping_client):
                        log.error(f"[{label}] 백엔드 응답 없음 — 자동 재시작 시도")
                        if not await _restart_backend():
                            raise StepFailed(
                                f"{label}: 백엔드 재시작 실패 — 수동 점검 필요"
                            ) from e
                        # 재시작 성공 — 다음 시도
                await asyncio.sleep(2)
                continue
            log.error(f"[{label}] 재시도까지 모두 실패")
            raise StepFailed(f"{label}: {e}") from e
        except Exception as e:
            log.warning(f"[{label}] 시도 {attempt}/2 실패: {e}")
            if attempt == 2:
                log.error(f"[{label}] 재시도까지 모두 실패")
                raise StepFailed(f"{label}: {e}") from e
            await asyncio.sleep(5)


async def _backend_alive(client: httpx.AsyncClient, timeout: float = 5.0) -> bool:
    """백엔드 살아있는지 빠른 ping. /api/auth/status 가 200 면 OK."""
    try:
        resp = await client.get(
            f"{BACKEND}/api/auth/status",
            timeout=httpx.Timeout(timeout),
        )
        return resp.status_code == 200
    except Exception:
        return False


async def _restart_backend() -> bool:
    """포트 8000 점유 프로세스 종료 + start.pyw 재실행. 30초 안에 alive 면 True.

    Windows 전용. PowerShell 한 번 호출로 끝냄.
    """
    import subprocess

    log.warning("백엔드 재시작 시도 — 포트 8000 점유 프로세스 종료")
    try:
        # 8000 포트 listen 중인 프로세스 모두 kill (uvicorn worker 포함)
        subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-Command",
                "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue "
                "| ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
            ],
            timeout=15,
            check=False,
        )
        await asyncio.sleep(2)

        start_pyw = _ROOT_DIR / "start.pyw"
        if not start_pyw.exists():
            log.error(f"start.pyw 없음 — 재시작 불가 ({start_pyw})")
            return False

        # DETACHED_PROCESS — 부모 (이 프로세스) 종료 시에도 백엔드 유지
        subprocess.Popen(
            ["pythonw.exe", str(start_pyw)],
            cwd=str(_ROOT_DIR),
            creationflags=0x00000200 | 0x00000008,
        )
    except Exception as e:
        log.error(f"백엔드 재시작 실패: {e}")
        return False

    # 30초 안에 alive 확인
    async with httpx.AsyncClient() as ping_client:
        for i in range(30):
            await asyncio.sleep(1)
            if await _backend_alive(ping_client):
                log.info(f"백엔드 재시작 완료 ({i+1}초)")
                return True

    log.error("백엔드 재시작 30초 내 응답 없음")
    return False


async def wait_task(client: httpx.AsyncClient, task_id: str, label: str) -> dict:
    """task_manager 의 task가 completed/failed 가 될 때까지 폴링.

    Watchdog (1단계 R-4): 폴링 연속 실패 시 백엔드 healthcheck → 죽었으면 재시작.
    재시작 후 task_id 는 유실 (in-memory) — caller 가 db_check 또는 verify_run 으로 확인.
    """
    if DRY_RUN or task_id == "DRYRUN":
        log.info(f"[DRY RUN] wait_task({label}, {task_id}) 즉시 통과")
        return {"status": "completed", "message": "dry-run skip"}

    deadline = datetime.utcnow().timestamp() + TASK_TIMEOUT
    last_msg = ""
    consecutive_fails = 0
    BACKEND_DEAD_THRESHOLD = 5  # 5회 연속 실패 (≈ 50초) → 백엔드 점검

    while True:
        if datetime.utcnow().timestamp() > deadline:
            raise StepFailed(f"{label} 태스크 타임아웃 ({TASK_TIMEOUT}초)")

        try:
            data = await _get(client, f"/api/tasks/{task_id}")
            consecutive_fails = 0  # 성공 시 리셋
        except Exception as e:
            consecutive_fails += 1
            log.warning(f"[{label}] 태스크 폴링 실패 {consecutive_fails}회: {e}")

            if consecutive_fails >= BACKEND_DEAD_THRESHOLD:
                log.warning(f"[{label}] {consecutive_fails}회 연속 실패 — 백엔드 점검")
                alive = await _backend_alive(client)
                if not alive:
                    log.error(f"[{label}] 백엔드 응답 없음 — 자동 재시작 시도")
                    if await _restart_backend():
                        # 재시작 성공 — task_id 유실되었을 가능성
                        # caller (recover/verify) 가 DB 로 결과 확인 후 재실행
                        raise StepFailed(
                            f"{label}: 백엔드 재시작 — task_id={task_id} 유실, "
                            f"recover.py 로 재실행 필요"
                        )
                    else:
                        raise StepFailed(f"{label}: 백엔드 재시작 실패 — 수동 점검 필요")
                # alive 면 일시 네트워크 blip — 계속 폴링
                consecutive_fails = 0

            await asyncio.sleep(POLL_INTERVAL)
            continue

        if data.get("error"):
            raise StepFailed(f"{label}: 태스크 조회 실패 — {data.get('error')}")

        status = data.get("status")
        msg = data.get("message", "")
        if msg != last_msg:
            log.info(
                f"[{label}] {status} - {msg} "
                f"({data.get('progress')}/{data.get('total')})"
            )
            last_msg = msg

        if status == "completed":
            return data
        if status == "failed":
            raise StepFailed(f"{label} 태스크 실패: {msg}")
        await asyncio.sleep(POLL_INTERVAL)


# ─── 단계들 ────────────────────────────────────────────

async def step_health_check(client: httpx.AsyncClient) -> None:
    log.info("=== STEP 1: 헬스체크 ===")
    try:
        await _get(client, "/api/auth/status", timeout=10)
    except Exception as e:
        raise StepFailed(f"백엔드 응답 없음 ({BACKEND}): {e}") from e

    # 디버그 Chrome (9222) 점검 — 없으면 자동 launch (Phase 2.5 V-1)
    await _ensure_chrome_debug()


async def _ensure_chrome_debug() -> None:
    """포트 9222 connect 시도 → 없으면 launch_chrome_debug.bat 자동 실행.

    헤드풀 GUI 환경 의존이라 사용자 로그인 세션이어야 함 (작업 스케줄러 Interactive 권한).
    실패해도 자동화는 계속 (browser_manager fallback).
    """
    import socket
    import subprocess
    from pathlib import Path

    def _port_open(host: str = "127.0.0.1", port: int = 9222, timeout: float = 1.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    if _port_open():
        log.info("디버그 Chrome 9222 살아있음 (CDP attach 사용 가능)")
        return

    bat_path = Path(__file__).parent / "launch_chrome_debug.bat"
    if not bat_path.exists():
        log.warning(f"launch_chrome_debug.bat 없음 — Chrome 디버그 스킵 ({bat_path})")
        return

    log.info(f"디버그 Chrome 자동 시작: {bat_path}")
    try:
        # CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS — 백엔드 워커와 분리된 GUI 프로세스
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path)],
            cwd=str(bat_path.parent.parent),
            creationflags=0x00000200 | 0x00000008,  # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        )
    except Exception as e:
        log.warning(f"Chrome 디버그 launch 실패 (browser_manager fallback): {e}")
        return

    # 30초 대기 후 재점검 (Chrome 첫 launch 는 5초 부족 — 4/29 case)
    for i in range(30):
        await asyncio.sleep(1)
        if _port_open():
            log.info(f"디버그 Chrome 9222 활성화 ({i+1}초)")
            return
    log.warning("디버그 Chrome 30초 내 응답 없음 — fallback")


async def _check_naver_api() -> tuple[bool, str]:
    """네이버 쇼핑 API 키 인증 점검. (ok, msg)."""
    cid = (os.getenv("NAVER_CLIENT_ID") or "").strip()
    csec = (os.getenv("NAVER_CLIENT_SECRET") or "").strip()
    if not cid or not csec:
        return False, "NAVER_CLIENT_ID/SECRET 미설정"
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(
                "https://openapi.naver.com/v1/search/shop.json",
                headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec},
                params={"query": "test", "display": 1},
            )
        if r.status_code == 200:
            return True, "OK"
        if r.status_code == 401:
            return False, "API 키 인증 실패 (401)"
        if r.status_code == 429:
            return False, "API 일일한도 초과 (429)"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def _check_naver_smartstore_session(
    client: httpx.AsyncClient,
) -> tuple[bool, str, int | None]:
    """naver-browser-profile 쿠키 디스크 검사 (네트워크 호출 없음, 빠름).

    백엔드의 /api/products/naver-session-check 호출 → (alive, details, days_left).
    """
    try:
        data = await _get(client, "/api/products/naver-session-check", timeout=5)
        return (
            bool(data.get("alive")),
            str(data.get("details") or "?"),
            data.get("days_left"),
        )
    except Exception as e:
        return False, f"점검 실패: {type(e).__name__}: {e}", None


async def _check_chrome_debug() -> tuple[bool, str]:
    """9222 포트 + /json/version 응답 확인."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=2):
            pass
    except Exception:
        return False, "포트 9222 closed"
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get("http://127.0.0.1:9222/json/version")
        if r.status_code == 200:
            data = r.json()
            return True, f"OK ({data.get('Browser','unknown')[:30]})"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def step_login_status(client: httpx.AsyncClient) -> None:
    """헬스체크 — 큐텐 로그인 + 네이버 API + 디버그 Chrome.

    각 항목 만료/실패 시 텔레그램 즉시 알림 후 CaptchaRequired raise.
    어느 항목 실패했는지 명시 → 사장님이 눈 뜨자마자 어떤 보안을 풀어야 하는지 즉시 인지.
    """
    log.info("=== STEP 2: 로그인 상태 확인 ===")

    # 1) 큐텐 (M01)
    qoo10_ok = qoo10_msg = ""
    try:
        data = await _get(client, "/api/auth/status", timeout=10)
        qoo10_ok = bool(data.get("logged_in"))
        if qoo10_ok:
            qoo10_msg = "OK"
        else:
            has_cookies = bool(data.get("has_cookies"))
            qoo10_msg = "쿠키는 있지만 logged_in=False" if has_cookies else "쿠키 없음"
    except Exception as e:
        qoo10_ok = False
        qoo10_msg = f"점검 실패: {type(e).__name__}: {e}"

    # 2) 네이버 API
    naver_ok, naver_msg = await _check_naver_api()

    # 3) 디버그 Chrome (CDP attach 위해)
    chrome_ok, chrome_msg = await _check_chrome_debug()

    # 4) Naver smartstore 세션 (naver-browser-profile 쿠키)
    naver_sess_ok, naver_sess_msg, naver_days_left = await _check_naver_smartstore_session(client)

    # keyword_only 모드는 STEP 5+ (smartstore detail fetch) 를 안 돔 → 세션 ✗ 여도 abort 안 함
    naver_sess_required = AUTOMATION_MODE == "full"

    # 모두 통과
    log.info(f"큐텐: {'✓' if qoo10_ok else '✗'} {qoo10_msg}")
    log.info(f"네이버 API: {'✓' if naver_ok else '✗'} {naver_msg}")
    log.info(f"디버그 Chrome: {'✓' if chrome_ok else '✗'} {chrome_msg}")
    log.info(f"Naver 세션: {'✓' if naver_sess_ok else '✗'} {naver_sess_msg}")
    if not naver_sess_ok and not naver_sess_required:
        log.warning(f"Naver 세션 ✗ — keyword_only 모드라 abort 하지 않음 (smartstore fetch 미사용)")

    if qoo10_ok and naver_ok and (naver_sess_ok or not naver_sess_required):
        # Chrome 은 critical 아님 (warning 만)
        if not chrome_ok:
            log.warning(f"디버그 Chrome 9222 비활성 — 한국 셀러 진입 차단 가능: {chrome_msg}")
        # D-7 임박 알림 (alive 지만 만료 임박 — 자동화는 진행). keyword_only 면 어차피 안 쓰니 skip.
        if naver_sess_required and naver_days_left is not None and naver_days_left <= 7:
            warn = (
                f"📌 Naver 세션 만료 임박 — D-{naver_days_left}\n"
                f"open_naver_login_chrome.bat 실행 → 재로그인 (로그인 유지 체크) → 창 닫기"
            )
            log.warning(warn)
            try:
                await notify.send(warn, level="warn")
            except Exception:
                pass
        return

    # 실패 시 — 어느 보안 풀어야 하는지 명시
    failed = []
    if not qoo10_ok: failed.append(f"큐텐 ({qoo10_msg})")
    if not naver_ok: failed.append(f"네이버 API ({naver_msg})")
    if not naver_sess_ok and naver_sess_required:
        failed.append(f"Naver 세션 ({naver_sess_msg}) → open_naver_login_chrome.bat 실행")
    if not chrome_ok: failed.append(f"Chrome9222 ({chrome_msg})")

    msg_lines = "\n".join(f"  - {f}" for f in failed)
    msg = f"보안 점검 실패\n{msg_lines}\n\n사장님 처리 후 자동화 재실행 필요."

    # 즉시 텔레그램 알림 (CaptchaRequired 가 main 에서도 alert 보내지만 여기서 미리)
    try:
        await notify.send(msg, level="auth")
    except Exception:
        pass

    raise CaptchaRequired(msg)


async def step_check_existing_keywords(
    client: httpx.AsyncClient, target_date: date
) -> int:
    """해당 날짜에 이미 수집된 키워드 수 반환. 0이면 수집 필요."""
    try:
        dates = await _get(client, "/api/keywords/dates")
    except Exception as e:
        log.warning(f"기존 키워드 체크 실패(무시, 새로 수집 진행): {e}")
        return 0

    target_str = str(target_date)
    for d in dates or []:
        if str(d.get("lookup_date")) == target_str:
            return int(d.get("count", 0))
    return 0


async def step_collect_trend(client: httpx.AsyncClient) -> None:
    log.info("=== STEP 3: 트렌드 키워드 수집 (01.종합 + 03.뷰티&화장품 + 07.식품, 비딩 포함) ===")

    async def _call() -> dict:
        return await _post(client, "/api/keywords/trend", {
            "categories": [1, 3, 7],     # 01.종합 + 03.뷰티&화장품 + 07.식품 (사장님 디폴트)
            "translate": True,
            "fill_total_products": True,
            "collect_bids": True,        # 야간엔 시간 여유 있으니 비딩까지
        })

    result = await with_retry(_call, label="트렌드 수집 시작")
    task_id = result.get("master_task_id") or result.get("task_id") or "DRYRUN"
    log.info(f"트렌드 수집 task_id={task_id}")
    await wait_task(client, task_id, label="트렌드 수집")


async def step_classify_categories(
    client: httpx.AsyncClient, target_date: date
) -> dict:
    """STEP 3.5 — LLM 카테고리 분류.

    best-effort: 실패하면 경고 로그 + 다음 단계 진행 (StepFailed raise 안 함).
    같은 키워드 중복은 API 가 unique 단위로 알아서 묶음.
    """
    log.info("=== STEP 3.5: 카테고리 분류 (LLM) ===")
    if not ENABLE_LLM_CATEGORY:
        log.info("ENABLE_LLM_CATEGORY=0 — 스킵")
        return {"skipped": True}

    try:
        result = await _post(client, "/api/keywords/classify-categories", {
            "date": str(target_date),
        })
    except Exception as e:
        log.warning(f"카테고리 분류 시작 실패 (best-effort 스킵): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates = result.get("candidates", 0)
    if not task_id:
        log.info(f"카테고리 분류 대상 0개 (이미 모두 분류됨)")
        return {"candidates": 0}

    log.info(f"카테고리 분류 task_id={task_id} (대상 {candidates}개 unique 키워드)")
    try:
        await wait_task(client, task_id, label="카테고리 분류")
        return {"task_id": task_id, "candidates": candidates}
    except Exception as e:
        log.warning(f"카테고리 분류 실패 (best-effort, 다음 단계 진행): {e}")
        return {"error": str(e), "candidates": candidates}


async def _resolve_categories(client: httpx.AsyncClient) -> list[str] | None:
    """카테고리 화이트리스트 우선순위: UserData → .env → None(전체).

    UserData 응답: {"data": {"value": ["03.뷰티&화장품", ...]}, ...}
    """
    # 1) UserData 시도
    try:
        d = await _get(client, "/api/user-data/auto_filter_categories", timeout=10)
        payload = d.get("data") or {}
        if isinstance(payload, dict):
            v = payload.get("value")
            if isinstance(v, list) and v:
                return [str(x).strip() for x in v if str(x).strip()]
    except Exception as e:
        log.warning(f"UserData auto_filter_categories 조회 실패 (env 폴백): {e}")
    # 2) env 폴백
    if AUTO_FILTER_CATEGORIES_ENV:
        return [c.strip() for c in AUTO_FILTER_CATEGORIES_ENV.split(",") if c.strip()]
    # 3) 미설정 → 전체 통과
    return None


# MMM-1: raw 큐텐 카테고리 blacklist 기본값 (사장님 사업 영역 X)
DEFAULT_CATEGORY_BLACKLIST = ["05.디지털", "08.엔터테인먼트&e티켓", "10.모바일"]


async def _resolve_category_blacklist(client: httpx.AsyncClient) -> list[str]:
    """raw 큐텐 카테고리 blacklist (디지털/엔터테인먼트 자동 제외).

    UserData → 기본값 (DEFAULT_CATEGORY_BLACKLIST)
    """
    try:
        d = await _get(client, "/api/user-data/auto_filter_category_blacklist", timeout=10)
        payload = d.get("data") or {}
        if isinstance(payload, dict):
            v = payload.get("value")
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
    except Exception as e:
        log.warning(f"UserData blacklist 조회 실패 (기본값): {e}")
    return DEFAULT_CATEGORY_BLACKLIST


async def _resolve_filter_thresholds(client: httpx.AsyncClient) -> tuple[float, float, int]:
    """자동 필터 임계값 조회. 우선순위: UserData > env > 하드코딩.

    UserData key 'auto_filter_thresholds' 데이터 모양:
        {"competition_max": 2.0, "kr_ratio_min": 0.3, "volume_min": 40}

    프론트 SettingsPage 슬라이더 → /api/user-data/auto_filter_thresholds 저장.
    """
    try:
        d = await _get(client, "/api/user-data/auto_filter_thresholds", timeout=10)
        payload = d.get("data") or {}
        if isinstance(payload, dict) and "competition_max" in payload:
            cm = float(payload.get("competition_max") or FILTER_COMPETITION_MAX)
            kr = float(payload.get("kr_ratio_min") or FILTER_KR_RATIO_MIN)
            vm = int(payload.get("volume_min") or FILTER_VOLUME_MIN)
            return cm, kr, vm
    except Exception as e:
        log.warning(f"UserData auto_filter_thresholds 조회 실패 (env 폴백): {e}")
    return FILTER_COMPETITION_MAX, FILTER_KR_RATIO_MIN, FILTER_VOLUME_MIN


async def _diagnose_filter_zero(client: httpx.AsyncClient, target_date: date) -> str:
    """STEP 4 가 0개일 때 — 임계값 문제인지 메타데이터 누락인지 진단.

    같은 endpoint 를 매우 느슨한 임계값으로 다시 호출 → total_candidates 비교.
    - loose 도 0 → 메타데이터 (search_volume / competition_intensity) 가 모두 0 — STEP 3 메타 채움 누락
    - loose 만 양수 → 임계값이 너무 빡빡 — 사장님 settings 점검
    """
    try:
        resp = await client.post(
            f"{BACKEND}/api/keywords/auto-filter",
            json={
                "competition_max": 999.0,
                "kr_ratio_min": 0.0,
                "search_volume_min": 0,
                "date": str(target_date),
                "brand_filter": "all",
            },
            timeout=httpx.Timeout(30.0),
        )
        loose = resp.json().get("total_candidates", 0)
    except Exception as e:
        return f"진단 실패: {e}"

    if loose == 0:
        return (
            f"메타데이터 누락 추정 — loose 임계값에서도 0개. "
            f"키워드의 search_volume/competition_intensity 가 모두 0 으로 보임. "
            f"STEP 3 트렌드 수집을 다시 (특히 fill_total_products=True, collect_bids=True) 실행해야 함."
        )
    return f"임계값 과다 — loose 에서는 {loose}개 통과. 사장님 settings 임계값 완화 필요."


async def step_auto_filter(client: httpx.AsyncClient, target_date: date) -> list[dict]:
    log.info("=== STEP 4: 자동 필터 ===")
    categories = await _resolve_categories(client)
    if categories:
        log.info(f"카테고리 화이트리스트: {categories}")
    else:
        log.info("카테고리 화이트리스트: (미설정 — 전체 통과)")

    cm, kr, vm = await _resolve_filter_thresholds(client)
    blacklist = await _resolve_category_blacklist(client)
    log.info(
        f"임계값: competition_max={cm} kr_ratio_min={kr} volume_min={vm} "
        f"(UserData → env → 하드코딩 순)"
    )
    if blacklist:
        log.info(f"카테고리 blacklist: {blacklist}")

    async def _call() -> dict:
        body = {
            "competition_max": cm,
            "kr_ratio_min": kr,
            "search_volume_min": vm,
            "date": str(target_date),
            "brand_filter": "all",  # 사용자 결정 2c — 표시만, 통과
        }
        if categories:
            body["categories"] = categories
        if blacklist:
            body["category_blacklist"] = blacklist
        return await _post(client, "/api/keywords/auto-filter", body)

    result = await with_retry(_call, label="자동 필터")

    if DRY_RUN:
        # 흐름 검증용 가짜 후보 3개
        return [
            {"keyword_jp": "サンプル1"},
            {"keyword_jp": "サンプル2"},
            {"keyword_jp": "サンプル3"},
        ]

    keywords = result.get("keywords") or []
    log.info(
        f"자동 필터 통과: {len(keywords)}개 "
        f"(전체 후보 {result.get('total_candidates')})"
    )
    return keywords


async def step_collect_domestic(
    client: httpx.AsyncClient, candidates: list[dict]
) -> int:
    log.info(f"=== STEP 5: 한국 상품 수집 ({len(candidates)}개 키워드) ===")
    keywords_jp = [c["keyword_jp"] for c in candidates if c.get("keyword_jp")]

    async def _call() -> dict:
        return await _post(client, "/api/recommendations/collect", {
            "keywords_jp": keywords_jp,
            "include_qoo10": True,
            "include_naver": True,
        })

    result = await with_retry(_call, label="한국 상품 수집 시작")
    task_id = result.get("task_id") or "DRYRUN"
    log.info(f"한국 상품 수집 task_id={task_id}")
    await wait_task(client, task_id, label="한국 상품 수집")
    return len(keywords_jp)


async def step_process_domestic_images(
    client: httpx.AsyncClient, target_date: date, candidates: list[dict],
) -> dict:
    """STEP 5.7 — 자동 필터 통과 키워드의 한국 상품 이미지 다운로드+비전+폴더링.

    best-effort: 실패해도 다음 단계 진행.
    """
    log.info("=== STEP 5.9: 한국 상품 이미지 처리 ===")
    if not ENABLE_DOMESTIC_IMAGES:
        log.info("ENABLE_DOMESTIC_IMAGES=0 — 스킵")
        return {"skipped": True}

    keywords_jp = [c["keyword_jp"] for c in candidates if c.get("keyword_jp")]
    if not keywords_jp:
        log.info("대상 키워드 0개 — 스킵")
        return {"candidates": 0}

    try:
        result = await _post(client, "/api/products/domestic/process-images", {
            "date": str(target_date),
            "keywords_jp": keywords_jp,
        })
    except Exception as e:
        log.warning(f"이미지 처리 시작 실패 (best-effort): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates_n = result.get("candidates", 0)
    if not task_id:
        log.info("이미지 처리 대상 0개")
        return {"candidates": 0}

    log.info(f"이미지 처리 task_id={task_id} (대상 {candidates_n}장)")
    try:
        await wait_task(client, task_id, label="이미지 처리")
        return {"task_id": task_id, "candidates": candidates_n}
    except Exception as e:
        log.warning(f"이미지 처리 실패 (best-effort): {e}")
        return {"error": str(e), "candidates": candidates_n}


async def step_translate_qoo10_names(
    client: httpx.AsyncClient, target_date: date
) -> dict:
    """STEP 5.4 — 큐텐 상품명 jp→ko 번역 (배치).

    이 단계 누락 시 시트의 "큐텐→한글" 컬럼이 비게 됨.
    """
    log.info("=== STEP 5.4: 큐텐 상품명 번역 (jp→ko) ===")
    try:
        result = await _post(client, "/api/products/qoo10/translate-names", {
            "date": str(target_date),
        })
    except Exception as e:
        log.warning(f"번역 시작 실패 (best-effort): {e}")
        return {"error": str(e)}
    task_id = result.get("task_id")
    candidates = result.get("candidates", 0)
    if not task_id:
        log.info(f"번역 대상 0건 (이미 처리됨)")
        return {"candidates": 0}
    log.info(f"번역 task_id={task_id} (대상 {candidates}개 unique 상품명)")
    try:
        await wait_task(client, task_id, label="큐텐 상품명 번역")
        return {"task_id": task_id, "candidates": candidates}
    except Exception as e:
        log.warning(f"번역 실패 (best-effort): {e}")
        return {"error": str(e), "candidates": candidates}


async def step_extract_set_counts(
    client: httpx.AsyncClient, target_date: date
) -> dict:
    """STEP 5.5 — 큐텐 상품 set_count 추출 (정규식 + LLM 폴백).

    best-effort: 실패해도 다음 단계 진행.
    """
    log.info("=== STEP 5.5: set_count 추출 ===")
    if not ENABLE_SET_COUNT_EXTRACTION:
        log.info("ENABLE_SET_COUNT_EXTRACTION=0 — 스킵")
        return {"skipped": True}

    try:
        result = await _post(client, "/api/products/qoo10/extract-set-counts", {
            "date": str(target_date),
        })
    except Exception as e:
        log.warning(f"set_count 추출 시작 실패 (best-effort 스킵): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates = result.get("candidates", 0)
    if not task_id:
        log.info("set_count 대상 0개 (이미 모두 처리됨)")
        return {"candidates": 0}

    log.info(f"set_count 추출 task_id={task_id} (대상 {candidates}개 unique 상품명)")
    try:
        await wait_task(client, task_id, label="set_count 추출")
        return {"task_id": task_id, "candidates": candidates}
    except Exception as e:
        log.warning(f"set_count 추출 실패 (best-effort): {e}")
        return {"error": str(e), "candidates": candidates}


async def step_collect_related_keywords(
    client: httpx.AsyncClient, candidates: list[dict]
) -> dict:
    """STEP 4.5 (R-5) — 자동 필터 통과 키워드 → M05 유사/연관 → expanded_keywords.

    트렌드 페이지 상위 670 키워드는 누적 랭킹이라 매일 거의 고정. M05 가 큐텐 ADPlus
    의 "유사" / "연관" 탭에서 키워드당 ~5+10 추출 → expanded_keywords 적재. 그 후
    STEP 5.8 expanded_search 가 한국 검색 → STEP 5.95 매칭까지 자연 흐름.

    best-effort. 실패해도 다음 단계 진행.
    """
    log.info("=== STEP 4.5: M05 유사/연관 키워드 (R-5) ===")
    if not ENABLE_RELATED_KEYWORDS:
        log.info("ENABLE_RELATED_KEYWORDS=0 — 스킵")
        return {"skipped": True}

    keywords_jp = [c["keyword_jp"] for c in candidates if c.get("keyword_jp")]
    if not keywords_jp:
        log.info("대상 키워드 0개 — 스킵")
        return {"candidates": 0}

    body = {
        "keywords_jp": keywords_jp,
        "max_per_parent": RELATED_KEYWORDS_MAX_PER_PARENT,
    }
    try:
        result = await _post(client, "/api/keywords/expand-related", body)
    except Exception as e:
        log.warning(f"M05 expand-related 시작 실패 (best-effort 스킵): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates_n = result.get("candidates", 0)
    if not task_id:
        log.info("M05 대상 0개")
        return {"candidates": 0}

    log.info(f"M05 expand-related task_id={task_id} (대상 {candidates_n}개 부모 키워드)")
    try:
        await wait_task(client, task_id, label="M05 유사/연관")
        return {"task_id": task_id, "candidates": candidates_n}
    except Exception as e:
        log.warning(f"M05 wait 실패 (best-effort): {e}")
        return {"error": str(e), "candidates": candidates_n}


async def step_shop_benchmark_sync(client: httpx.AsyncClient) -> dict:
    """STEP 4.8 (U) — 등록된 큐텐 샵에서 자동 fetch + 신규 상품 표시.

    UserData "shop_urls" 의 모든 샵 → m13 scraper → last_seen 비교 → is_new 플래그.
    결과는 shop_cache UserData 갱신 → ShopBenchmarkPage 자동 로드.

    best-effort. 실패해도 워크플로우 계속.
    """
    log.info("=== STEP 4.8: 샵 벤치마크 자동 동기화 (U) ===")
    if not ENABLE_SHOP_BENCHMARK_SYNC:
        log.info("ENABLE_SHOP_BENCHMARK_SYNC=0 — 스킵")
        return {"skipped": True}

    body = {
        "shop_urls": [],  # 비우면 UserData "shop_urls" 사용
        "limit_per_shop": SHOP_BENCHMARK_LIMIT,
        "sort_type": SHOP_BENCHMARK_SORT,
    }
    try:
        result = await _post(client, "/api/automation/shop-benchmark-sync", body)
    except Exception as e:
        log.warning(f"샵 벤치마크 시작 실패 (best-effort 스킵): {e}")
        return {"error": str(e)}

    if result.get("error"):
        log.warning(f"샵 벤치마크 — {result['error']}")
        return result
    log.info(
        f"샵 벤치마크 완료: 샵 {result.get('shops', 0)}개 / 신규 상품 {result.get('total_new', 0)}건"
    )
    return result


async def step_url_batch_regenerate(client: httpx.AsyncClient) -> dict:
    """STEP 4.7 (C) — 시트의 URL 있고 데이터 미수집 행 자동 처리.

    URL 도메인별 라우팅 (백엔드 _do_regenerate):
      - Naver: 크롬 확장 (메인 Chrome 켜져있어야)
      - Coupang: 백엔드 Scrapling (Chrome 무관)

    keyword_only / full 둘 다에서 동작 — 시트 따로 흐름이라 모드 영향 없음.
    best-effort. 실패해도 워크플로우 계속.
    """
    log.info("=== STEP 4.7: URL 일괄 재생성 (시트 미수집 URL 자동 처리) ===")
    if not ENABLE_URL_BATCH_REGENERATE:
        log.info("ENABLE_URL_BATCH_REGENERATE=0 — 스킵")
        return {"skipped": True}

    body = {
        "limit": URL_BATCH_LIMIT,
        "include_jp_detail": URL_BATCH_INCLUDE_JP_DETAIL,
        "skip_if_filled": True,
    }
    try:
        result = await _post(client, "/api/automation/url-batch-regenerate", body)
    except Exception as e:
        log.warning(f"URL 일괄 시작 실패 (best-effort 스킵): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    total = result.get("total", 0)
    if not task_id:
        log.info(f"URL 일괄 — 처리할 행 없음 ({result.get('message', '')})")
        return {"total": 0}

    log.info(f"URL 일괄 task_id={task_id} (대상 {total}건)")
    try:
        final = await wait_task(client, task_id, label="URL 일괄 재생성")
        log.info(f"URL 일괄 완료: {final.get('message', '')}")
        return {"task_id": task_id, "total": total, "result": final}
    except Exception as e:
        log.warning(f"URL 일괄 wait 실패 (best-effort): {e}")
        return {"error": str(e), "total": total}


async def step_brand_expand(
    client: httpx.AsyncClient, target_date: date, candidates: list[dict]
) -> dict:
    """STEP 5.7 — 브랜드 키워드 확장 (Phase 1-D Q+R-2).

    is_brand=1 키워드의 큐텐 상위 N개 product_name 으로부터 specific keyword 3-5개 추출.
    best-effort. brand 키워드 0개면 즉시 통과.
    """
    log.info("=== STEP 5.7: 브랜드 키워드 확장 (Phase 1-D) ===")
    if not ENABLE_BRAND_EXPAND:
        log.info("ENABLE_BRAND_EXPAND=0 — 스킵")
        return {"skipped": True}

    brand_kws = [c for c in candidates if c.get("is_brand")]
    if not brand_kws:
        log.info("brand 키워드 0개 — 스킵")
        return {"candidates": 0}

    body = {
        "date": str(target_date),
        "qoo10_date": str(target_date),
        "top_n": BRAND_EXPAND_TOP_N,
    }
    try:
        result = await _post(client, "/api/keywords/expand-brand", body)
    except Exception as e:
        log.warning(f"brand expand 시작 실패 (best-effort 스킵): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates_n = result.get("candidates", 0)
    if not task_id:
        log.info("brand expand 대상 0개 (이미 모두 처리됨)")
        return {"candidates": 0}

    log.info(f"brand expand task_id={task_id} (대상 {candidates_n}개 brand 키워드)")
    try:
        await wait_task(client, task_id, label="brand expand")
        return {"task_id": task_id, "candidates": candidates_n}
    except Exception as e:
        log.warning(f"brand expand 실패 (best-effort): {e}")
        return {"error": str(e), "candidates": candidates_n}


async def step_expanded_search(client: httpx.AsyncClient) -> dict:
    """STEP 5.8 — 확장 키워드 → 한국 검색 (Phase 1-D S-1).

    expanded_keywords 테이블의 keyword_kr 들로 m08 검색해서 한국 상품 풀 보강.
    best-effort.
    """
    log.info("=== STEP 5.8: 확장 키워드 한국 검색 (Phase 1-D) ===")
    if not ENABLE_EXPANDED_SEARCH:
        log.info("ENABLE_EXPANDED_SEARCH=0 — 스킵")
        return {"skipped": True}

    body = {"max_results": EXPANDED_SEARCH_MAX_RESULTS}
    try:
        result = await _post(client, "/api/keywords/expanded/run-search", body)
    except Exception as e:
        log.warning(f"expanded 검색 시작 실패 (best-effort 스킵): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates_n = result.get("candidates", 0)
    if not task_id:
        log.info("expanded 검색 대상 0개")
        return {"candidates": 0}

    log.info(f"expanded 검색 task_id={task_id} (대상 {candidates_n}개 확장 키워드)")
    try:
        await wait_task(client, task_id, label="expanded 검색")
        return {"task_id": task_id, "candidates": candidates_n}
    except Exception as e:
        log.warning(f"expanded 검색 실패 (best-effort): {e}")
        return {"error": str(e), "candidates": candidates_n}


async def step_match_images(
    client: httpx.AsyncClient, target_date: date, candidates: list[dict],
) -> dict:
    """STEP 5.95 — 큐텐 ↔ 한국 cover 1:N 매칭 (R-2 통합).

    expanded keyword 가 만든 확장 풀까지 포함해서 매칭. accepted/rejected 결정.
    best-effort.
    """
    log.info("=== STEP 5.95: 이미지+텍스트 매칭 (R-2) ===")
    if not ENABLE_MATCH_IMAGES:
        log.info("ENABLE_MATCH_IMAGES=0 — 스킵")
        return {"skipped": True}

    keywords_jp = [c["keyword_jp"] for c in candidates if c.get("keyword_jp")]
    if not keywords_jp:
        log.info("대상 키워드 0개 — 스킵")
        return {"candidates": 0}

    body = {
        "date": str(target_date),
        "per_qoo10_top_n": MATCH_IMAGES_TOP_N,
        "keywords_jp": keywords_jp,
    }
    try:
        result = await _post(client, "/api/recommendations/match-images", body)
    except Exception as e:
        log.warning(f"match-images 시작 실패 (best-effort 스킵): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates_n = result.get("candidates", 0)
    scanned = result.get("scanned_qoo10", 0)
    if not task_id:
        log.info(f"match-images 대상 0개 (스캔 {scanned})")
        return {"candidates": 0, "scanned": scanned}

    log.info(
        f"match-images task_id={task_id} "
        f"(스캔 {scanned}장 → 비교 쌍 {candidates_n}건, threshold={result.get('threshold')})"
    )
    try:
        await wait_task(client, task_id, label="match-images")
        return {"task_id": task_id, "candidates": candidates_n, "scanned": scanned}
    except Exception as e:
        log.warning(f"match-images 실패 (best-effort): {e}")
        return {"error": str(e), "candidates": candidates_n}


async def step_generate_qoo10_content(
    client: httpx.AsyncClient, target_date: date, candidates: list[dict]
) -> dict:
    """STEP 6.0 — 큐텐 SEO 콘텐츠 자동 생성 (Phase 4-B).

    accepted 매칭 큐텐 상품 대상으로 title_jp/tags/option_name/marketing_points
    한 번에 생성 (qwen3:14b). 검수 페이지 enrich 에 사용됨.
    best-effort.
    """
    log.info("=== STEP 6.0: 큐텐 SEO 콘텐츠 생성 (Phase 4-B) ===")
    if not ENABLE_QOO10_CONTENT:
        log.info("ENABLE_QOO10_CONTENT=0 — 스킵")
        return {"skipped": True}

    keywords_jp = [c["keyword_jp"] for c in candidates if c.get("keyword_jp")]
    if not keywords_jp:
        log.info("대상 키워드 0개 — 스킵")
        return {"candidates": 0}

    body = {
        "date": str(target_date),
        "keywords_jp": keywords_jp,
        "only_accepted": True,
    }
    try:
        result = await _post(client, "/api/products/qoo10/generate-content", body)
    except Exception as e:
        log.warning(f"큐텐 콘텐츠 시작 실패 (best-effort 스킵): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates_n = result.get("candidates", 0)
    if not task_id:
        log.info("큐텐 콘텐츠 대상 0개")
        return {"candidates": 0}

    log.info(f"큐텐 콘텐츠 task_id={task_id} (대상 {candidates_n}개 큐텐 상품)")
    try:
        await wait_task(client, task_id, label="큐텐 콘텐츠 생성")
        return {"task_id": task_id, "candidates": candidates_n}
    except Exception as e:
        log.warning(f"큐텐 콘텐츠 실패 (best-effort): {e}")
        return {"error": str(e), "candidates": candidates_n}


async def step_auto_learning_inject(
    client: httpx.AsyncClient, target_date: date
) -> dict:
    """STEP 5.6 (KKK-1 B) — swap 사례 기반 preferred kw 자동 주입.

    expanded_search 전에 호출 → 사장님이 학습한 keyword_kr 가 자동 검색됨.
    """
    log.info("=== STEP 5.6: 자동 학습 — preferred kw 주입 (KKK-1 B) ===")
    if not ENABLE_AUTO_LEARNING:
        log.info("ENABLE_AUTO_LEARNING=0 — 스킵")
        return {"skipped": True}
    try:
        result = await _post(client, "/api/recommendations/auto-learning/inject-preferred", {
            "date": str(target_date),
        })
        inserted = result.get("inserted", 0)
        if inserted:
            log.info(f"학습 — {inserted}건 preferred kw 주입")
        else:
            log.info(f"학습 — {result.get('message') or '주입 0건'}")
        return result
    except Exception as e:
        log.warning(f"자동 학습 inject 실패 (best-effort): {e}")
        return {"error": str(e)}


async def step_auto_learning_autotune(
    client: httpx.AsyncClient,
) -> dict:
    """STEP 7 (KKK-1 C) — quality 임계값 swap_rate 기반 자동 조정.

    매주 1회 권장. 매일 호출해도 변동 작아 상관없음 (sample < 5 면 skip).
    """
    log.info("=== STEP 7: 자동 학습 — quality 임계값 auto-tune (KKK-1 C) ===")
    if not ENABLE_AUTO_LEARNING:
        log.info("ENABLE_AUTO_LEARNING=0 — 스킵")
        return {"skipped": True}
    try:
        result = await _post(client, "/api/recommendations/auto-learning/autotune", {})
        decision = result.get("decision", "?")
        if decision == "tightened":
            log.info(f"학습 — 임계값 ↑ {result.get('before')} → {result.get('after')} "
                     f"(swap_rate {result.get('swap_rate')})")
        elif decision == "loosened":
            log.info(f"학습 — 임계값 ↓ {result.get('before')} → {result.get('after')} "
                     f"(swap_rate {result.get('swap_rate')})")
        else:
            log.info(f"학습 — {decision} ({result.get('message') or ''})")
        return result
    except Exception as e:
        log.warning(f"자동 학습 autotune 실패 (best-effort): {e}")
        return {"error": str(e)}


async def step_build_jp_detail(
    client: httpx.AsyncClient, target_date: date,
) -> dict:
    """STEP 6.05 (FFFF-1) — accepted/needs_review 매칭 candidate 마다 JP 상세 카피 + 한글 번역 자동 생성.

    qoo10-jp-detail-master.md 가이드 적용. ~30 후보 × ~2분 = ~1h 소요.
    """
    log.info("=== STEP 6.05: JP 상세 카피 자동 (FFFF-1) ===")
    if not ENABLE_JP_DETAIL:
        log.info("ENABLE_JP_DETAIL=0 — 스킵")
        return {"skipped": True}
    try:
        result = await _post(client, "/api/products/qoo10/build-jp-detail", {
            "date": str(target_date),
        })
    except Exception as e:
        log.warning(f"JP 상세 시작 실패 (best-effort): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates = result.get("candidates", 0)
    if not task_id:
        log.info(f"JP 상세 대상 0건 ({result.get('message', '')})")
        return {"candidates": 0}
    log.info(f"JP 상세 task_id={task_id} (대상 {candidates}건)")
    try:
        await wait_task(client, task_id, label="JP 상세 카피")
    except Exception as e:
        log.warning(f"JP 상세 wait 실패 (best-effort): {e}")
        return {"error": str(e), "task_id": task_id}
    return {"task_id": task_id, "candidates": candidates}


async def step_match_retry(
    client: httpx.AsyncClient, target_date: date
) -> dict:
    """STEP 6.6 (HHH-1) — image_score 낮은 candidate alt 키워드 재검색 + 재매칭.

    auto-build 가 storage 만든 후 호출. snapshot 의 best image_score < 0.5 인
    keyword 에 대해 LLM 으로 alt 한국어 키워드 2~3개 생성 → Naver 재검색 →
    cheapest qoo10 vs 새 한국 cover 매칭. 결과 accepted DMC 행 INSERT.
    이후 candidate-images 빌드가 새 cheapest 반영.
    """
    log.info("=== STEP 6.6: 매칭 retry (HHH-1) ===")
    if not ENABLE_MATCH_RETRY:
        log.info("ENABLE_MATCH_RETRY=0 — 스킵")
        return {"skipped": True}

    try:
        result = await _post(client, "/api/recommendations/match-retry", {
            "date": str(target_date),
        })
    except Exception as e:
        log.warning(f"retry 시작 실패 (best-effort): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    if not task_id:
        log.info(f"retry 실행 안됨: {result}")
        return result

    log.info(f"retry task_id={task_id}")
    try:
        await wait_task(client, task_id, label="매칭 retry")
    except Exception as e:
        log.warning(f"retry wait 실패 (best-effort): {e}")
        return {"error": str(e), "task_id": task_id}

    # 결과 조회
    try:
        summary = (await client.get(
            f"{BACKEND}/api/recommendations/match-retry/{target_date}"
        )).json()
        improved = summary.get("improved", 0)
        retried = summary.get("retried", 0)
        log.info(f"retry 완료 — retried {retried}, 개선 {improved}")
        return {"task_id": task_id, **summary}
    except Exception as e:
        log.warning(f"retry 결과 조회 실패: {e}")
        return {"task_id": task_id, "error": str(e)}


async def step_candidate_images(
    client: httpx.AsyncClient, target_date: date
) -> dict:
    """STEP 6.7 (DDD-1) — auto-build 후보별 keyword 폴더 + meta.json.

    auto-build 가 storage 만든 후 호출. cheapest cover + alt cover 2~3개.
    """
    log.info("=== STEP 6.7: 후보 이미지 폴더 (DDD-1) ===")
    if not ENABLE_CANDIDATE_IMAGES:
        log.info("ENABLE_CANDIDATE_IMAGES=0 — 스킵")
        return {"skipped": True}

    try:
        result = await _post(client, "/api/products/candidate-images/build", {
            "date": str(target_date),
        })
    except Exception as e:
        log.warning(f"후보 이미지 시작 실패 (best-effort): {e}")
        return {"error": str(e)}

    processed = result.get("processed", 0)
    log.info(f"후보 이미지 폴더: {processed}건")
    return {"candidates": processed}


async def step_verify_set_counts(
    client: httpx.AsyncClient, target_date: date, candidates: list[dict],
) -> dict:
    """STEP 6.5 — 마진 N%+ 큐텐 상품 set_count 비전 검증.

    best-effort: 실패해도 다음 단계 진행.
    """
    log.info(f"=== STEP 6.5: set_count 비전 검증 (마진≥{SET_COUNT_VERIFY_MIN_MARGIN*100:.0f}%) ===")
    if not ENABLE_SET_COUNT_VERIFY:
        log.info("ENABLE_SET_COUNT_VERIFY=0 — 스킵")
        return {"skipped": True}

    keywords_jp = [c["keyword_jp"] for c in candidates if c.get("keyword_jp")]
    if not keywords_jp:
        log.info("대상 키워드 0개 — 스킵")
        return {"candidates": 0}

    try:
        result = await _post(client, "/api/products/qoo10/verify-set-counts", {
            "date": str(target_date),
            "min_margin_rate": SET_COUNT_VERIFY_MIN_MARGIN,
            "keywords_jp": keywords_jp,
        })
    except Exception as e:
        log.warning(f"비전 검증 시작 실패 (best-effort): {e}")
        return {"error": str(e)}

    task_id = result.get("task_id")
    candidates_n = result.get("candidates", 0)
    if not task_id:
        log.info("비전 검증 대상 0개")
        return {"candidates": 0, "scanned": result.get("scanned", 0)}

    log.info(f"비전 검증 task_id={task_id} (대상 {candidates_n}장 / 스캔 {result.get('scanned', 0)})")
    try:
        await wait_task(client, task_id, label="set_count 비전 검증")
        return {"task_id": task_id, "candidates": candidates_n}
    except Exception as e:
        log.warning(f"비전 검증 실패 (best-effort): {e}")
        return {"error": str(e), "candidates": candidates_n}


async def step_auto_build(
    client: httpx.AsyncClient, candidates: list[dict], target_date: date
) -> dict:
    log.info("=== STEP 6: 추천 자동 빌드 ===")
    keywords_jp = [c["keyword_jp"] for c in candidates if c.get("keyword_jp")]

    async def _call() -> dict:
        return await _post(client, "/api/recommend/auto-build", {
            "keywords_jp": keywords_jp,
            "date": str(target_date),
            "min_margin_rate": MIN_MARGIN_RATE,
        })

    result = await with_retry(_call, label="추천 자동 빌드")

    if DRY_RUN:
        return {
            "count": 0,
            "total_candidates": 0,
            "storage_key": f"last_auto_collected:{target_date}",
        }

    log.info(
        f"추천 빌드 완료: {result.get('count')}개 "
        f"(전체 후보 {result.get('total_candidates')}, 저장키 {result.get('storage_key')})"
    )
    return result


# ─── 메인 ──────────────────────────────────────────────

def _format_summary(
    started: datetime,
    ended: datetime,
    trend_status: str,
    classify_result: dict,
    filtered_count: int,
    domestic_count: int,
    image_result: dict,
    set_count_result: dict,
    build_result: dict,
    verify_result: dict,
    brand_expand_result: dict | None = None,
    expanded_search_result: dict | None = None,
    match_result: dict | None = None,
    content_result: dict | None = None,
) -> str:
    elapsed = ended - started
    elapsed_str = str(elapsed).split(".", 1)[0]

    if classify_result.get("skipped"):
        classify_line = "스킵 (ENABLE_LLM_CATEGORY=0)"
    elif classify_result.get("error"):
        classify_line = f"실패: {classify_result['error'][:60]}"
    else:
        n = classify_result.get("candidates", 0)
        classify_line = f"{n}개 unique 키워드 분류" if n else "대상 0개"

    if set_count_result.get("skipped"):
        sc_line = "스킵 (ENABLE_SET_COUNT_EXTRACTION=0)"
    elif set_count_result.get("error"):
        sc_line = f"실패: {set_count_result['error'][:60]}"
    else:
        n = set_count_result.get("candidates", 0)
        sc_line = f"{n}개 unique 상품명 처리" if n else "대상 0개"

    if image_result.get("skipped"):
        img_line = "스킵 (ENABLE_DOMESTIC_IMAGES=0)"
    elif image_result.get("error"):
        img_line = f"실패: {image_result['error'][:60]}"
    else:
        n = image_result.get("candidates", 0)
        img_line = f"{n}장 다운로드+평가" if n else "대상 0개"

    if verify_result.get("skipped"):
        vf_line = "스킵 (ENABLE_SET_COUNT_VERIFY=0)"
    elif verify_result.get("error"):
        vf_line = f"실패: {verify_result['error'][:60]}"
    else:
        n = verify_result.get("candidates", 0)
        vf_line = f"{n}장 비전 검증" if n else "마진 임계값 도달 0개"

    def _line(r: dict | None, off_label: str, unit: str) -> str:
        if not r: return "(미실행)"
        if r.get("skipped"): return f"스킵 ({off_label})"
        if r.get("error"): return f"실패: {r['error'][:60]}"
        n = r.get("candidates", 0)
        return f"{n}{unit}" if n else "대상 0"

    be_line = _line(brand_expand_result, "ENABLE_BRAND_EXPAND=0", "개 brand")
    es_line = _line(expanded_search_result, "ENABLE_EXPANDED_SEARCH=0", "개 확장 키워드")
    if match_result and not match_result.get("skipped") and not match_result.get("error"):
        mt_line = (
            f"{match_result.get('candidates', 0)}쌍 비교 "
            f"(스캔 {match_result.get('scanned', 0)}장)"
        )
    else:
        mt_line = _line(match_result, "ENABLE_MATCH_IMAGES=0", "쌍")

    qc_line = _line(content_result, "ENABLE_QOO10_CONTENT=0", "개 큐텐 콘텐츠")

    # 핵심만 — 모바일 한눈에 (~150자)
    final_count = build_result.get('count', 0)
    total_count = build_result.get('total_candidates', 0)
    return (
        f"야간 자동화 완료 ({elapsed_str})\n"
        f"📊 후보 {final_count}/{total_count} (필터통과 {filtered_count})\n"
        f"📋 시트: {BACKEND}/recommend-products"
    )


async def main_async() -> int:
    started = datetime.now()
    target_date = TARGET_DATE_OVERRIDE or date.today()
    setup_logging(target_date.strftime("%Y%m%d"))

    mode_label = "DRY RUN" if DRY_RUN else "실제 실행"
    log.info(f"=== 야간 자동화 시작 ({mode_label}) ===")

    await notify.send(
        f"야간 자동화 시작 ({started.strftime('%H:%M')})\n"
        f"모드: {mode_label}\n"
        f"백엔드: {BACKEND}",
        level="info",
    )

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        try:
            await step_health_check(client)
            await step_login_status(client)

            existing = await step_check_existing_keywords(client, target_date)
            if existing > 0:
                log.info(
                    f"=== STEP 3: 트렌드 수집 스킵 — {target_date} 키워드 "
                    f"{existing}개 이미 존재 ==="
                )
                trend_status = f"스킵 (기존 {existing}개)"
            else:
                await step_collect_trend(client)
                trend_status = "수집 완료"

            classify_result = await step_classify_categories(client, target_date)

            candidates = await step_auto_filter(client, target_date)

            if not candidates:
                # R-4 2단계 검증: 필터 0개 원인 진단 — 임계값 vs 메타데이터 누락 구분
                diag = await _diagnose_filter_zero(client, target_date)
                msg = (
                    f"자동 필터 통과 키워드 0개. {diag}\n"
                    f"(competition_max={FILTER_COMPETITION_MAX}, "
                    f"kr_ratio_min={FILTER_KR_RATIO_MIN}, "
                    f"volume_min={FILTER_VOLUME_MIN})"
                )
                log.warning(msg)
                await notify.send(msg, level="warn")
                return 0

            # R-5 STEP 4.5 — M05 유사/연관 키워드 → expanded_keywords (best-effort)
            related_result = await step_collect_related_keywords(client, candidates)

            # U STEP 4.8 — 샵 벤치마크 자동 동기화 (best-effort)
            shop_sync_result = await step_shop_benchmark_sync(client)

            # C STEP 4.7 — 시트 URL 일괄 재생성 (Naver 확장 / Coupang 백엔드, best-effort)
            url_batch_result = await step_url_batch_regenerate(client)

            # R-6 — 자동화 범위 제어. 사장님 결정: 매칭/이미지/auto-build 불안정으로 홀드.
            # 기본 mode "keyword_only" 면 여기서 종료. STEP 5+ 는 사장님이 수동으로 진행.
            if AUTOMATION_MODE == "keyword_only":
                ended = datetime.now()
                elapsed_str = str(ended - started).split(".", 1)[0]
                related_n = (related_result or {}).get("candidates", 0)
                url_batch_total = (url_batch_result or {}).get("total", 0)
                url_batch_msg = ((url_batch_result or {}).get("result") or {}).get("message", "")
                shop_new = (shop_sync_result or {}).get("total_new", 0)
                shop_n = (shop_sync_result or {}).get("shops", 0)
                summary = (
                    f"야간 자동화 완료 ({elapsed_str}) — keyword_only 모드\n"
                    f"트렌드 {trend_status} / 분류 {classify_result.get('candidates', 0)} / "
                    f"필터 통과 {len(candidates)} / M05 부모 {related_n}\n"
                    f"샵 벤치마크: {shop_n}개 샵 / 신규 {shop_new}\n"
                    f"URL 일괄: {url_batch_msg or f'{url_batch_total}건 처리'}\n"
                    f"키워드 RD 완료"
                )
                await notify.send(summary, level="ok")
                log.info(f"=== 야간 자동화 완료 (keyword_only, {elapsed_str}) ===")
                return 0

            # full 모드 (레거시) — STEP 5+ 진행
            domestic_kw_count = await step_collect_domestic(client, candidates)
            # MMM-1: 큐텐 상품명 jp→ko 번역 (시트 "큐텐→한글" 컬럼 채움)
            await step_translate_qoo10_names(client, target_date)
            set_count_result = await step_extract_set_counts(client, target_date)

            # Phase 1-D: brand expand → expanded search → image dl+vision → match
            #   - brand expand 가 큐텐 product_name → specific keyword 생성
            #   - expanded search 가 한국 상품 풀 보강 (1:N 매칭 후보 확장)
            #   - process_domestic_images 가 새로 들어온 한국 cover 까지 다운+vision
            #   - match-images 가 1:N 매칭으로 accepted/rejected 결정
            brand_expand_result = await step_brand_expand(client, target_date, candidates)
            # KKK-1 B — 사장님 swap 학습 → preferred kw 자동 주입 (expanded_keywords)
            await step_auto_learning_inject(client, target_date)
            expanded_search_result = await step_expanded_search(client)
            image_result = await step_process_domestic_images(client, target_date, candidates)
            match_result = await step_match_images(client, target_date, candidates)

            # Phase 4-B 큐텐 SEO 콘텐츠 — auto_build 전에 생성 (검수 페이지 enrich 용)
            content_result = await step_generate_qoo10_content(client, target_date, candidates)
            # FFFF-1: JP 상세 카피 + 한글 번역 (qoo10-jp-detail-master.md 가이드)
            await step_build_jp_detail(client, target_date)

            build_result = await step_auto_build(client, candidates, target_date)
            # HHH-1 — image_score 낮은 candidate alt 키워드 재검색 + 재매칭
            #         (재매칭이 accepted DMC 만들면 다음 candidate-images 가 새 cheapest 사용)
            retry_result = await step_match_retry(client, target_date)
            if retry_result.get("improved", 0) > 0:
                # alt 매칭 결과 반영을 위해 auto_build 재실행 (cheapest_domestic 갱신)
                build_result = await step_auto_build(client, candidates, target_date)
            # DDD-1 — auto-build storage 후 candidates 만 keyword 폴더로
            await step_candidate_images(client, target_date)
            verify_result = await step_verify_set_counts(client, target_date, candidates)

            # KKK-1 C — quality 임계값 자동 조정 (매주 수렴)
            await step_auto_learning_autotune(client)

            ended = datetime.now()
            await notify.send(
                _format_summary(
                    started, ended, trend_status, classify_result,
                    len(candidates), domestic_kw_count, image_result,
                    set_count_result, build_result, verify_result,
                    brand_expand_result, expanded_search_result, match_result,
                    content_result,
                ),
                level="ok",
            )
            log.info("=== 야간 자동화 완료 ===")
            return 0

        except CaptchaRequired as e:
            log.error(f"로그인 실패: {e}")
            await notify.send(
                f"CAPTCHA 발생, 사용자 처리 필요\n원인: {e}\n수동 로그인 후 재실행 필요.",
                level="auth",
            )
            return 2
        except StepFailed as e:
            log.error(f"단계 실패로 중단: {e}")
            await notify.send(f"야간 자동화 실패\n{e}", level="error")
            return 3
        except Exception as e:
            log.error(f"예상치 못한 오류: {e}")
            log.error(traceback.format_exc())
            await notify.send(
                f"야간 자동화 예상치 못한 오류\n{type(e).__name__}: {e}",
                level="error",
            )
            return 4


def main() -> int:
    global DRY_RUN, TARGET_DATE_OVERRIDE
    parser = argparse.ArgumentParser(description="Qoo10 야간 자동화")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="POST 호출은 모킹만 하고 GET·로깅·알림 흐름 통합 테스트",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="대상 날짜 (YYYY-MM-DD). 미지정 시 오늘. 누락된 일자 보충 실행에 사용.",
    )
    args = parser.parse_args()

    DRY_RUN = args.dry_run
    if DRY_RUN:
        # notify.py 가 [DRY RUN] 프리픽스 붙이도록 환경변수 세팅
        os.environ["AUTOMATION_DRY_RUN"] = "1"
    if args.date:
        TARGET_DATE_OVERRIDE = datetime.strptime(args.date, "%Y-%m-%d").date()

    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
