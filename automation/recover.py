"""야간 자동화 복구 / 누락 단계 재실행.

사용 시나리오:
  1) 야간 자동화가 중간에 hang 또는 죽었을 때 (예: 5/1 STEP 5.95 후 멈춤).
  2) verify_run.py 가 누락 항목 발견하고 자동 호출.
  3) 사장님이 출근 후 수동 호출 — `python automation/recover.py 2026-05-01`.

기본 동작: 주어진 날짜의 자동화 산출물을 점검 → 누락 STEP 만 재실행.
  - STEP 6 (auto-build): 항상 재실행 (idempotent, 빠름)
  - STEP 6.0 (qoo10 콘텐츠): SEO 콘텐츠 비어있는 큐텐상품 있으면 실행
  - STEP 6.6 (match-retry): 항상 재실행 (HHH-1)
  - STEP 6.7 (candidate-images): image/{date}/ 폴더 없거나 비어있으면 실행
  - STEP 6.5 (verify): always best-effort
  - STEP 7 (autotune): always best-effort

옵션:
  --from-step <name>   : 강제로 특정 단계부터 (예: --from-step 6.0)
  --only <name,...>    : 특정 단계만 (콤마구분)
  --dry-run            : POST 모킹

종료코드:
  0 — 모든 단계 성공 또는 best-effort 통과
  1 — 후보 0개 (auto-filter 통과 X) — 임계값 점검 필요
  2 — 백엔드 헬스체크 실패
  3 — 단계 실행 중 치명 오류
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

import httpx

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR))

# daily_workflow 의 step 함수 재사용 (load_dotenv, BACKEND, log 등 초기화도 함께)
import daily_workflow as dw  # noqa: E402
import notify  # noqa: E402

ROOT_DIR = _THIS_DIR.parent
IMAGE_DIR = ROOT_DIR / "image"


# ─── 점검 함수 ─────────────────────────────────────────

async def _has_auto_build(client: httpx.AsyncClient, target_date: date) -> bool:
    """STEP 6 결과 (/api/recommend/auto-collected/{date}) 에 후보 1개 이상."""
    try:
        resp = await client.get(
            f"{dw.BACKEND}/api/recommend/auto-collected/{target_date}",
            timeout=httpx.Timeout(15.0),
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        items = data.get("items") or data.get("candidates") or []
        return len(items) > 0
    except Exception as e:
        dw.log.warning(f"auto-build 점검 실패: {e}")
        return False


def _candidate_images_done(target_date: date) -> bool:
    """image/{date}/ 폴더에 keyword 서브폴더 1개 이상."""
    folder = IMAGE_DIR / str(target_date)
    if not folder.exists():
        return False
    subs = [p for p in folder.iterdir() if p.is_dir()]
    return len(subs) > 0


# ─── 메인 복구 흐름 ─────────────────────────────────────

async def recover(
    target_date: date,
    only: set[str] | None = None,
    from_step: str | None = None,
) -> int:
    dw.setup_logging(target_date.strftime("%Y%m%d"))
    started = datetime.now()
    dw.log.info(f"=== 자동화 복구 시작 ({target_date}) ===")

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        # 1) 헬스체크
        try:
            await dw.step_health_check(client)
        except Exception as e:
            dw.log.error(f"백엔드 헬스체크 실패: {e}")
            await notify.send(f"복구 실패 — 백엔드 죽어있음\n{e}", level="error")
            return 2

        # 2) auto-filter 재실행 (idempotent) → candidates 획득
        candidates = await dw.step_auto_filter(client, target_date)
        if not candidates:
            msg = (
                f"복구 — 자동 필터 통과 0개. 임계값 또는 search_volume null 점검 필요\n"
                f"(competition_max={dw.FILTER_COMPETITION_MAX}, "
                f"kr_ratio_min={dw.FILTER_KR_RATIO_MIN}, "
                f"volume_min={dw.FILTER_VOLUME_MIN})"
            )
            dw.log.warning(msg)
            await notify.send(msg, level="warn")
            return 1

        # 3) 단계별 실행 결정
        steps_to_run: list[str] = []
        # 4.5 = M05 expand-related (R-5). 6.x 는 기존.
        full_pipeline = ["4.5", "6.0", "6", "6.6", "6.7", "6.5", "7"]

        if only:
            steps_to_run = [s for s in full_pipeline if s in only]
        elif from_step:
            if from_step not in full_pipeline:
                dw.log.error(f"--from-step 값 잘못됨: {from_step} (가능: {full_pipeline})")
                return 3
            idx = full_pipeline.index(from_step)
            steps_to_run = full_pipeline[idx:]
        else:
            # 자동 감지
            has_build = await _has_auto_build(client, target_date)
            has_folder = _candidate_images_done(target_date)
            dw.log.info(
                f"점검 결과: auto-build={'✓' if has_build else '✗'}, "
                f"image/{target_date}/={'✓' if has_folder else '✗'}"
            )
            # auto-build / 6.7 누락이면 풀 파이프라인 재실행 (이미 done 인 단계는 idempotent)
            if not has_build or not has_folder:
                steps_to_run = full_pipeline
            else:
                dw.log.info("모든 핵심 산출물 존재 — 복구 불필요")
                return 0

        dw.log.info(f"실행 단계: {steps_to_run}")

        # 4) 단계 실행
        results: dict[str, dict] = {}
        try:
            if "4.5" in steps_to_run:
                results["4.5"] = await dw.step_collect_related_keywords(client, candidates)
            if "6.0" in steps_to_run:
                results["6.0"] = await dw.step_generate_qoo10_content(client, target_date, candidates)
            if "6" in steps_to_run:
                results["6"] = await dw.step_auto_build(client, candidates, target_date)
            if "6.6" in steps_to_run:
                retry_result = await dw.step_match_retry(client, target_date)
                results["6.6"] = retry_result
                if retry_result.get("improved", 0) > 0 and "6" in steps_to_run:
                    dw.log.info("retry 개선 → auto-build 재실행")
                    results["6"] = await dw.step_auto_build(client, candidates, target_date)
            if "6.7" in steps_to_run:
                results["6.7"] = await dw.step_candidate_images(client, target_date)
            if "6.5" in steps_to_run:
                results["6.5"] = await dw.step_verify_set_counts(client, target_date, candidates)
            if "7" in steps_to_run:
                results["7"] = await dw.step_auto_learning_autotune(client)
        except dw.StepFailed as e:
            dw.log.error(f"복구 단계 실패: {e}")
            await notify.send(f"복구 실패 — 단계 중단\n{e}", level="error")
            return 3
        except Exception as e:
            dw.log.error(f"예상치 못한 복구 오류: {e}")
            await notify.send(f"복구 — 예상치 못한 오류\n{type(e).__name__}: {e}", level="error")
            return 3

    # 5) 요약
    elapsed = str(datetime.now() - started).split(".", 1)[0]
    dw.log.info(f"=== 자동화 복구 완료 ({elapsed}) ===")

    summary_lines = [f"복구 완료 ({elapsed})"]
    for step in steps_to_run:
        r = results.get(step, {})
        if r.get("skipped"):
            summary_lines.append(f"  STEP {step}: 스킵")
        elif r.get("error"):
            summary_lines.append(f"  STEP {step}: ✗ {r['error'][:50]}")
        else:
            n = r.get("candidates") or r.get("count") or r.get("processed") or 0
            summary_lines.append(f"  STEP {step}: ✓ {n}")
    await notify.send("\n".join(summary_lines), level="ok")
    return 0


# ─── CLI ──────────────────────────────────────────────

def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"날짜 형식 잘못됨 (YYYY-MM-DD): {s}") from e


def main() -> int:
    parser = argparse.ArgumentParser(description="자동화 복구 / 누락 단계 재실행")
    parser.add_argument("date", type=_parse_date, help="대상 날짜 (YYYY-MM-DD)")
    parser.add_argument("--from-step", dest="from_step", default=None,
                        help="이 단계부터 강제 실행 (6.0/6/6.6/6.7/6.5/7)")
    parser.add_argument("--only", default=None,
                        help="특정 단계만 (콤마구분)")
    parser.add_argument("--dry-run", action="store_true", help="POST 모킹")
    args = parser.parse_args()

    if args.dry_run:
        dw.DRY_RUN = True

    only = None
    if args.only:
        only = {s.strip() for s in args.only.split(",") if s.strip()}

    return asyncio.run(recover(args.date, only=only, from_step=args.from_step))


if __name__ == "__main__":
    sys.exit(main())
