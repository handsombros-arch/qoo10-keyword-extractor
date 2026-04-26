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

# automation/.env 로드 (.env 가 없으면 OS 환경변수만 사용)
load_dotenv(_THIS_DIR / ".env")

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
MIN_MARGIN_RATE = float(_env("MIN_MARGIN_RATE", "0.10"))


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


async def step_login_status(client: httpx.AsyncClient) -> None:
    log.info("=== STEP 2: 로그인 상태 확인 ===")
    data = await _get(client, "/api/auth/status", timeout=10)
    if data.get("logged_in"):
        log.info("로그인 OK")
        return

    has_cookies = bool(data.get("has_cookies"))
    if has_cookies:
        raise CaptchaRequired(
            "쿠키는 있지만 logged_in=False. 캡차 또는 세션 만료 가능성."
        )
    raise CaptchaRequired("쿠키 없음. 수동 로그인 필요.")


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


async def step_auto_filter(client: httpx.AsyncClient, target_date: date) -> list[dict]:
    log.info("=== STEP 4: 자동 필터 ===")

    async def _call() -> dict:
        return await _post(client, "/api/keywords/auto-filter", {
            "competition_max": FILTER_COMPETITION_MAX,
            "kr_ratio_min": FILTER_KR_RATIO_MIN,
            "search_volume_min": FILTER_VOLUME_MIN,
            "date": str(target_date),
        })

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
    filtered_count: int,
    domestic_count: int,
    build_result: dict,
) -> str:
    elapsed = ended - started
    elapsed_str = str(elapsed).split(".", 1)[0]
    return (
        f"야간 자동화 완료\n"
        f"시작: {started.strftime('%Y-%m-%d %H:%M')}\n"
        f"종료: {ended.strftime('%H:%M')} (소요 {elapsed_str})\n\n"
        f"트렌드 수집: {trend_status}\n"
        f"필터 통과 키워드: {filtered_count}개\n"
        f"한국상품 수집 키워드: {domestic_count}개\n"
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
            build_result = await step_auto_build(client, candidates, target_date)

            ended = datetime.now()
            await notify.send(
                _format_summary(
                    started, ended, trend_status,
                    len(candidates), domestic_kw_count, build_result,
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
