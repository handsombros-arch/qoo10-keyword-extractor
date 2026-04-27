"""비전 호출 일별 비용 추적 + 한도 보호.

- 비용 합산 소스: logs/llm_calls/{YYYY-MM-DD}.jsonl 의 vision 도메인 호출
  (기존 LLM logger 가 모든 호출 토큰을 기록 중. 별도 카운터 불필요)
- 한도 초과 시 BudgetExceededError → 호출부에서 catch 해 그 호출만 스킵
- 일자별 1회 Telegram 알림 (state file: logs/llm_calls/budget_alerted_{date}.flag)

PC별 한도 (jsonl 은 PC 로컬). 두 PC 합산은 future work.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_BUDGET_USD = 2.0
_DEFAULT_INPUT_PRICE = 0.075   # per 1M tokens
_DEFAULT_OUTPUT_PRICE = 0.30
_VISION_DOMAIN = "vision"


class BudgetExceededError(RuntimeError):
    """일일 비전 비용 한도 초과 시 raise."""


def _budget_usd() -> float:
    try:
        return float(os.getenv("VISION_DAILY_BUDGET_USD", str(_DEFAULT_BUDGET_USD)))
    except ValueError:
        return _DEFAULT_BUDGET_USD


def _input_price() -> float:
    try:
        return float(os.getenv("VISION_INPUT_PRICE_PER_1M", str(_DEFAULT_INPUT_PRICE)))
    except ValueError:
        return _DEFAULT_INPUT_PRICE


def _output_price() -> float:
    try:
        return float(os.getenv("VISION_OUTPUT_PRICE_PER_1M", str(_DEFAULT_OUTPUT_PRICE)))
    except ValueError:
        return _DEFAULT_OUTPUT_PRICE


def _log_dir() -> Path:
    """프로젝트 루트의 logs/llm_calls/. logger.py 와 같은 위치 규칙."""
    raw = os.getenv("LLM_LOG_DIR", "logs/llm_calls")
    p = Path(raw)
    if not p.is_absolute():
        # backend/app/services/llm/_budget.py → 4단계 위
        project_root = Path(__file__).resolve().parents[4]
        p = project_root / p
    return p


def _today_jsonl() -> Path:
    return _log_dir() / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"


def _alert_flag() -> Path:
    return _log_dir() / f"budget_alerted_{datetime.now().strftime('%Y-%m-%d')}.flag"


def _tokens_to_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * _input_price() + output_tokens * _output_price()) / 1_000_000


def today_vision_cost_usd() -> float:
    """오늘자 jsonl 에서 vision 도메인 호출의 누적 비용 (USD)."""
    path = _today_jsonl()
    if not path.exists():
        return 0.0

    total = 0.0
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("domain") != _VISION_DOMAIN:
                    continue
                if not rec.get("ok"):
                    continue  # 실패 호출은 비용 0 가정 (보수적)
                in_t = rec.get("input_tokens") or 0
                out_t = rec.get("output_tokens") or 0
                total += _tokens_to_usd(int(in_t), int(out_t))
    except Exception as e:
        logger.warning(f"[budget] jsonl 읽기 실패 ({e}) — 0 으로 처리")
        return 0.0

    return total


async def assert_budget_or_raise() -> None:
    """한도 초과 시 BudgetExceededError. 초과 첫 1회 Telegram 알림."""
    used = today_vision_cost_usd()
    budget = _budget_usd()
    if used < budget:
        return

    # 초과 — 알림 (1일 1회만)
    flag = _alert_flag()
    if not flag.exists():
        try:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(f"{datetime.now().isoformat()}\n", encoding="utf-8")
            await _notify_exceeded(used, budget)
        except Exception as e:
            logger.warning(f"[budget] 알림 실패 (무시): {e}")

    raise BudgetExceededError(
        f"비전 일별 한도 초과: 사용 ${used:.4f} / 한도 ${budget:.2f}. "
        f"내일 자정까지 차단."
    )


async def _notify_exceeded(used: float, budget: float) -> None:
    """automation/notify.py 의 send 사용. 모듈 경로 수동 추가."""
    project_root = Path(__file__).resolve().parents[4]
    automation_dir = str(project_root)
    if automation_dir not in sys.path:
        sys.path.insert(0, automation_dir)
    try:
        from automation.notify import send  # type: ignore
    except ImportError:
        logger.warning("[budget] automation.notify import 실패 — 콘솔만")
        print(
            f"⚠️ 비전 일별 한도 초과: ${used:.4f}/${budget:.2f}",
            file=sys.stderr,
            flush=True,
        )
        return

    msg = (
        f"비전(Gemini Vision) 일별 한도 초과\n"
        f"사용: ${used:.4f}\n한도: ${budget:.2f}\n"
        f"오늘 남은 호출은 차단됩니다. 내일 자정에 자동 리셋."
    )
    await send(msg, level="warn")


def budget_status() -> dict:
    """디버깅/대시보드용 — 사용량/한도/잔액."""
    used = today_vision_cost_usd()
    budget = _budget_usd()
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "used_usd": round(used, 6),
        "budget_usd": budget,
        "remaining_usd": round(max(0.0, budget - used), 6),
        "exceeded": used >= budget,
        "input_price_per_1m": _input_price(),
        "output_price_per_1m": _output_price(),
    }


__all__ = [
    "BudgetExceededError",
    "today_vision_cost_usd",
    "assert_budget_or_raise",
    "budget_status",
]
