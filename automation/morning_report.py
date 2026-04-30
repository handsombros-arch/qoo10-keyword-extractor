"""야간 자동화 결과 요약 → Telegram + Slack 동시 전송.

매일 08:00 Windows 작업 스케줄러로 자동 실행.

데이터 소스:
  - logs/automation_YYYYMMDD.log           — 실행 로그 (마지막 줄 + 에러 카운트)
  - 백엔드 GET /api/recommend/auto-collected/{date}  — candidate 수
  - 백엔드 GET /api/recommendations/match-retry/{date}  — retry 결과
  - 백엔드 GET /api/sheet/corrections/metrics       — 학습 진행
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

# .env 로드 (프로젝트 root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "automation"))
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(_PROJECT_ROOT / "backend" / ".env")
except Exception:
    pass

import httpx  # noqa: E402

import notify  # noqa: E402

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
LOG_DIR = _PROJECT_ROOT / "logs"


def _read_log_summary(target_date: date) -> dict:
    """log file 마지막 줄 + ERROR/WARN 카운트."""
    log_path = LOG_DIR / f"automation_{target_date.strftime('%Y%m%d')}.log"
    if not log_path.exists():
        return {"exists": False, "path": str(log_path)}
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return {"exists": True, "error": str(e)}
    lines = text.splitlines()
    err = sum(1 for l in lines if "[ERROR]" in l)
    warn = sum(1 for l in lines if "[WARNING]" in l)
    last_lines = [l for l in lines[-10:] if l.strip()]
    started = next((l for l in lines if "야간 자동화 시작" in l), "")
    completed = next((l for l in reversed(lines) if "야간 자동화 완료" in l), "")
    last_step = ""
    for l in reversed(lines):
        m = re.search(r"=== (STEP [\d.]+: [^=]+) ===", l)
        if m:
            last_step = m.group(1)
            break
    return {
        "exists": True,
        "path": str(log_path),
        "size_kb": log_path.stat().st_size // 1024,
        "lines": len(lines),
        "errors": err,
        "warnings": warn,
        "started": started[:120],
        "completed": completed[:120],
        "last_step": last_step,
        "last_lines": last_lines,
    }


async def _fetch_review(client: httpx.AsyncClient, target_date: date) -> dict:
    try:
        r = await client.get(f"{BACKEND}/api/recommend/auto-collected/{target_date}", timeout=10)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        data = r.json()
        cands = data.get("candidates") or []
        return {
            "candidates": len(cands),
            "best_margin": max((c.get("margin", {}).get("margin_rate") or 0) for c in cands) if cands else 0,
            "avg_margin": (sum((c.get("margin", {}).get("margin_rate") or 0) for c in cands) / len(cands)) if cands else 0,
        }
    except Exception as e:
        return {"error": str(e)}


async def _fetch_retry(client: httpx.AsyncClient, target_date: date) -> dict:
    try:
        r = await client.get(f"{BACKEND}/api/recommendations/match-retry/{target_date}", timeout=10)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        d = r.json()
        if "error" in d:
            return d
        return {
            "retried": d.get("retried", 0),
            "improved": d.get("improved", 0),
            "accepted": d.get("accepted", 0),
        }
    except Exception as e:
        return {"error": str(e)}


async def _fetch_metrics(client: httpx.AsyncClient) -> dict:
    try:
        r = await client.get(f"{BACKEND}/api/sheet/corrections/metrics", timeout=10)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _format_message(target_date: date, log: dict, review: dict, retry: dict, metrics: dict) -> tuple[str, str]:
    """(message, level) — level: ok/warn/error."""
    lines: list[str] = []
    lines.append(f"🌅 야간 자동화 결과 — {target_date}")
    lines.append("")

    # 로그 상태
    if not log.get("exists"):
        lines.append(f"⚠️ 로그 없음 — 자동화 미실행 의심")
        lines.append(f"   path={log.get('path')}")
        return "\n".join(lines), "error"

    # 완료 여부
    if log.get("completed"):
        lines.append(f"✅ 완료 ({log.get('errors',0)} ERR / {log.get('warnings',0)} WARN)")
    elif log.get("last_step"):
        lines.append(f"⚠️ 미완료 — 마지막: {log['last_step']}")
        lines.append(f"   ({log.get('errors',0)} ERR / {log.get('warnings',0)} WARN)")
    else:
        lines.append(f"❌ 시작도 못함 (로그만 있음)")

    # 후보 결과
    if "error" not in review:
        cands = review.get("candidates", 0)
        avg_m = review.get("avg_margin", 0) * 100
        best_m = review.get("best_margin", 0) * 100
        lines.append(f"📊 후보 {cands}개 | 평균 마진 {avg_m:.1f}% | 최고 {best_m:.1f}%")
    else:
        lines.append(f"📊 후보 조회 실패: {review.get('error')}")

    # retry 결과
    if "error" not in retry and retry.get("retried"):
        lines.append(f"🔄 매칭 retry — {retry.get('retried')}건 시도, "
                     f"{retry.get('improved')}개 개선, "
                     f"{retry.get('accepted')}개 accepted")

    # 학습 metrics
    if "error" not in metrics and metrics.get("total"):
        acc = metrics.get("ai_accuracy_estimate")
        acc_s = f"{acc*100:.0f}%" if acc is not None else "-"
        lines.append(f"🧠 누적 수정 {metrics.get('total')}건 | AI 정확도 ~{acc_s} | "
                     f"7일 swap {metrics.get('swap_count_recent_7d', 0)}건")

    lines.append("")
    lines.append(f"📋 시트: {BACKEND}/recommend-products")
    lines.append(f"📁 폴더: image\\{target_date}\\")

    if log.get("errors", 0) > 5:
        return "\n".join(lines), "error"
    if log.get("errors", 0) > 0 or not log.get("completed"):
        return "\n".join(lines), "warn"
    return "\n".join(lines), "ok"


async def main() -> int:
    target_date = date.today()
    log_summary = _read_log_summary(target_date)

    async with httpx.AsyncClient() as client:
        review = await _fetch_review(client, target_date)
        retry = await _fetch_retry(client, target_date)
        metrics = await _fetch_metrics(client)

    msg, level = _format_message(target_date, log_summary, review, retry, metrics)
    ok = await notify.send(msg, level=level)
    print(f"[morning_report] sent={ok} level={level}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
