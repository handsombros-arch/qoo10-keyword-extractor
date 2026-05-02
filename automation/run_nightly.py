"""야간 자동화 + 검증 + 자동 복구 통합 래퍼.

기존: Task Scheduler → daily_workflow.py
신규: Task Scheduler → run_nightly.py
        ├─ daily_workflow.py 실행 (필요 시 1회 재실행)
        ├─ verify_run.py 로 산출물 검증
        └─ 누락 발견 시 recover.py 자동 호출

설계 의도: daily_workflow 가 중간에 죽거나 (5/1 케이스: 백엔드 alive 인데 워크플로우 hang),
         backend 가 일시 hang 됐다가 복귀해도, 출근 전까지 자가 진단 + 회복까지 수행.

Task Scheduler 등록 (PowerShell):
    setup_scheduler.ps1 -Time "03:00" -IncludeChromeDebug -Wrapper

다음 옵션 자동 적용:
- daily_workflow 종료코드 0 또는 3 (StepFailed) → verify 실행
- daily_workflow 종료코드 2 (CAPTCHA) 또는 비정상 종료 → 알림 후 verify 실행
- 종료코드 0 으로 끝났어도 verify 실패 시 recover 호출
- 마지막에 morning_report 자동 호출 (사장님 출근 시 텔레그램 요약)

CLI:
    python automation/run_nightly.py            # 오늘 날짜
    python automation/run_nightly.py 2026-05-01 # 특정 날짜 (복구 전용)
    python automation/run_nightly.py --skip-workflow 2026-05-01  # workflow 스킵, verify+recover 만
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_THIS_DIR))

import notify  # type: ignore  # noqa: E402

PYTHON = sys.executable
WORKFLOW_PY = _THIS_DIR / "daily_workflow.py"
VERIFY_PY = _THIS_DIR / "verify_run.py"
RECOVER_PY = _THIS_DIR / "recover.py"
MORNING_PY = _THIS_DIR / "morning_report.py"


def _run(args: list[str], log_label: str) -> int:
    """subprocess 로 실행, 종료코드 반환. stdout/stderr 는 inherit (워커 로그파일에 기록)."""
    print(f"[run_nightly] {log_label}: {' '.join(args)}", flush=True)
    proc = subprocess.run(args, cwd=str(_ROOT_DIR))
    print(f"[run_nightly] {log_label} 종료코드={proc.returncode}", flush=True)
    return proc.returncode


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _send_notify(msg: str, level: str = "info") -> None:
    try:
        await notify.send(msg, level=level)
    except Exception as e:
        print(f"[run_nightly] 알림 실패 (무시): {e}", flush=True)


async def main_async(args) -> int:
    target_date = args.date or date.today()
    started = datetime.now()

    await _send_notify(
        f"야간 자동화 (래퍼) 시작 ({started.strftime('%H:%M')}, {target_date})",
        level="info",
    )

    workflow_rc = 0
    if not args.skip_workflow:
        # 1) daily_workflow.py 실행
        workflow_rc = _run([PYTHON, str(WORKFLOW_PY)], "daily_workflow")

        # 비정상 종료 (예: KeyboardInterrupt = -1, OS kill = -9 등) 시 1회 재시도
        if workflow_rc not in (0, 2, 3):
            print(f"[run_nightly] 비정상 종료 ({workflow_rc}) — 60초 후 1회 재시도", flush=True)
            await _send_notify(
                f"workflow 비정상 종료 (rc={workflow_rc}) — 1회 재시도",
                level="warn",
            )
            await asyncio.sleep(60)
            workflow_rc = _run([PYTHON, str(WORKFLOW_PY)], "daily_workflow (재시도)")

        if workflow_rc == 2:
            # CAPTCHA — 자동 진행 불가, verify/recover 도 의미 없음
            await _send_notify(
                "CAPTCHA 감지 — 사장님 수동 처리 필요. verify/recover 스킵.",
                level="auth",
            )
            return 2

    # 2) verify_run.py — 누락 시 recover 자동 호출 (--recover 플래그)
    verify_rc = _run(
        [PYTHON, str(VERIFY_PY), str(target_date), "--recover"],
        "verify_run (--recover)",
    )

    # 3) morning_report (있으면)
    if MORNING_PY.exists():
        _run([PYTHON, str(MORNING_PY)], "morning_report")

    elapsed = str(datetime.now() - started).split(".", 1)[0]
    if verify_rc == 0:
        await _send_notify(
            f"야간 자동화 + 자가 회복 완료 ({elapsed})\n"
            f"workflow rc={workflow_rc} verify rc=0",
            level="ok",
        )
        return 0

    # verify 가 회복 시도 후에도 실패 — 수동 개입 필요
    await _send_notify(
        f"야간 자동화 일부 실패 — 출근 후 점검 필요 ({elapsed})\n"
        f"workflow rc={workflow_rc} verify rc={verify_rc}",
        level="error",
    )
    return verify_rc


def main() -> int:
    parser = argparse.ArgumentParser(description="야간 자동화 + 자가 회복 통합 래퍼")
    parser.add_argument("date", nargs="?", type=_parse_date, default=None,
                        help="대상 날짜 (기본: 오늘)")
    parser.add_argument("--skip-workflow", action="store_true",
                        help="daily_workflow 스킵, verify+recover 만")
    args = parser.parse_args()

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
