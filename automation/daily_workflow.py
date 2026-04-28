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
ENABLE_DOMESTIC_IMAGES = _env("ENABLE_DOMESTIC_IMAGES", "1") == "1"

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

# 자동 필터 카테고리 화이트리스트 (콤마구분). 비어있으면 UserData 우선 → 그것도 없으면 모두 통과.
AUTO_FILTER_CATEGORIES_ENV = _env("AUTO_FILTER_CATEGORIES", "")


DRY_RUN = False
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
    """1회 재시도 후 실패하면 StepFailed 발생."""
    for attempt in (1, 2):
        try:
            return await coro_factory()
        except Exception as e:
            log.warning(f"[{label}] 시도 {attempt}/2 실패: {e}")
            if attempt == 2:
                log.error(f"[{label}] 재시도까지 모두 실패")
                raise StepFailed(f"{label}: {e}") from e
            await asyncio.sleep(5)


async def wait_task(client: httpx.AsyncClient, task_id: str, label: str) -> dict:
    """task_manager 의 task가 completed/failed 가 될 때까지 폴링."""
    if DRY_RUN or task_id == "DRYRUN":
        log.info(f"[DRY RUN] wait_task({label}, {task_id}) 즉시 통과")
        return {"status": "completed", "message": "dry-run skip"}

    deadline = datetime.utcnow().timestamp() + TASK_TIMEOUT
    last_msg = ""
    while True:
        if datetime.utcnow().timestamp() > deadline:
            raise StepFailed(f"{label} 태스크 타임아웃 ({TASK_TIMEOUT}초)")

        try:
            data = await _get(client, f"/api/tasks/{task_id}")
        except Exception as e:
            log.warning(f"[{label}] 태스크 폴링 실패(재시도): {e}")
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

    # 5초 대기 후 재점검 (로드 시간)
    for i in range(10):
        await asyncio.sleep(1)
        if _port_open():
            log.info(f"디버그 Chrome 9222 활성화 ({i+1}초)")
            return
    log.warning("디버그 Chrome 5초 내 응답 없음 — fallback")


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

    # 모두 통과
    log.info(f"큐텐: {'✓' if qoo10_ok else '✗'} {qoo10_msg}")
    log.info(f"네이버 API: {'✓' if naver_ok else '✗'} {naver_msg}")
    log.info(f"디버그 Chrome: {'✓' if chrome_ok else '✗'} {chrome_msg}")

    if qoo10_ok and naver_ok:
        # Chrome 은 critical 아님 (warning 만)
        if not chrome_ok:
            log.warning(f"디버그 Chrome 9222 비활성 — 한국 셀러 진입 차단 가능: {chrome_msg}")
        return

    # 실패 시 — 어느 보안 풀어야 하는지 명시
    failed = []
    if not qoo10_ok: failed.append(f"큐텐 ({qoo10_msg})")
    if not naver_ok: failed.append(f"네이버 ({naver_msg})")
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
    log.info("=== STEP 3: 트렌드 키워드 수집 (전체 카테고리, 비딩 포함) ===")

    async def _call() -> dict:
        return await _post(client, "/api/keywords/trend", {
            "categories": [0],          # 0 = 전체
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


async def step_auto_filter(client: httpx.AsyncClient, target_date: date) -> list[dict]:
    log.info("=== STEP 4: 자동 필터 ===")
    categories = await _resolve_categories(client)
    if categories:
        log.info(f"카테고리 화이트리스트: {categories}")
    else:
        log.info("카테고리 화이트리스트: (미설정 — 전체 통과)")

    cm, kr, vm = await _resolve_filter_thresholds(client)
    log.info(
        f"임계값: competition_max={cm} kr_ratio_min={kr} volume_min={vm} "
        f"(UserData → env → 하드코딩 순)"
    )

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

    return (
        f"야간 자동화 완료\n"
        f"시작: {started.strftime('%Y-%m-%d %H:%M')}\n"
        f"종료: {ended.strftime('%H:%M')} (소요 {elapsed_str})\n\n"
        f"트렌드 수집: {trend_status}\n"
        f"카테고리 분류: {classify_line}\n"
        f"필터 통과 키워드: {filtered_count}개\n"
        f"한국상품 수집 키워드: {domestic_count}개\n"
        f"set_count 추출: {sc_line}\n"
        f"브랜드 확장: {be_line}\n"
        f"확장 검색: {es_line}\n"
        f"이미지 처리: {img_line}\n"
        f"이미지+텍스트 매칭: {mt_line}\n"
        f"큐텐 SEO 콘텐츠: {qc_line}\n"
        f"set_count 비전 검증: {vf_line}\n"
        f"마진 통과 후보: {build_result.get('count', 0)}개 "
        f"(전체 {build_result.get('total_candidates', 0)})\n"
        f"저장 키: {build_result.get('storage_key', '')}\n\n"
        f"📊 출근 후 시트 빌드: {BACKEND}/recommend-products"
    )


async def main_async() -> int:
    started = datetime.now()
    target_date = date.today()
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
                msg = (
                    f"자동 필터 통과 키워드 0개. 임계값 점검 필요\n"
                    f"(competition_max={FILTER_COMPETITION_MAX}, "
                    f"kr_ratio_min={FILTER_KR_RATIO_MIN}, "
                    f"volume_min={FILTER_VOLUME_MIN})"
                )
                log.warning(msg)
                await notify.send(msg, level="warn")
                return 0

            domestic_kw_count = await step_collect_domestic(client, candidates)
            set_count_result = await step_extract_set_counts(client, target_date)

            # Phase 1-D: brand expand → expanded search → image dl+vision → match
            #   - brand expand 가 큐텐 product_name → specific keyword 생성
            #   - expanded search 가 한국 상품 풀 보강 (1:N 매칭 후보 확장)
            #   - process_domestic_images 가 새로 들어온 한국 cover 까지 다운+vision
            #   - match-images 가 1:N 매칭으로 accepted/rejected 결정
            brand_expand_result = await step_brand_expand(client, target_date, candidates)
            expanded_search_result = await step_expanded_search(client)
            image_result = await step_process_domestic_images(client, target_date, candidates)
            match_result = await step_match_images(client, target_date, candidates)

            # Phase 4-B 큐텐 SEO 콘텐츠 — auto_build 전에 생성 (검수 페이지 enrich 용)
            content_result = await step_generate_qoo10_content(client, target_date, candidates)

            build_result = await step_auto_build(client, candidates, target_date)
            verify_result = await step_verify_set_counts(client, target_date, candidates)

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
    global DRY_RUN
    parser = argparse.ArgumentParser(description="Qoo10 야간 자동화")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="POST 호출은 모킹만 하고 GET·로깅·알림 흐름 통합 테스트",
    )
    args = parser.parse_args()

    DRY_RUN = args.dry_run
    if DRY_RUN:
        # notify.py 가 [DRY RUN] 프리픽스 붙이도록 환경변수 세팅
        os.environ["AUTOMATION_DRY_RUN"] = "1"

    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
