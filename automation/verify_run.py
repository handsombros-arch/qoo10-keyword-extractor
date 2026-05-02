"""야간 자동화 산출물 검증 (3단계).

주어진 날짜의 자동화가 정상 완료됐는지 점검.
점검 항목:
  C1. 키워드 수집 — /api/keywords/dates 에 target_date 존재 + 키워드 수
  C2. 자동 필터 통과 후보 — auto-filter 재실행 (idempotent) → 1개 이상
  C3. auto-build snapshot — /api/review/{date} 가 candidates ≥ 1 반환
  C4. candidate-images 폴더 — image/{date}/ 에 keyword 서브폴더 ≥ 1
  C5. 큐텐 SEO 콘텐츠 — review payload 의 candidates 중 qoo10_title_jp 채워진 비율
  C6. set_count 검증 — review payload 의 set_count 검증 비율 (best-effort)

종료코드:
  0 — 모든 핵심 항목 통과
  1 — 누락 항목 있음 (자동 회복 필요) — 출력 첫 줄에 권장 STEP 리스트
  2 — 백엔드 unreachable

사용:
  python automation/verify_run.py 2026-05-01
  python automation/verify_run.py 2026-05-01 --json   # 결과 JSON
  python automation/verify_run.py 2026-05-01 --recover # 누락 시 recover.py 자동 호출
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx

# Windows CMD cp949 회피 — utf-8 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

_THIS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_THIS_DIR))

import daily_workflow as dw  # type: ignore  # noqa: E402

IMAGE_DIR = _ROOT_DIR / "image"

# 검증 항목별 → 누락 시 권장 recover STEP
STEP_FOR_CHECK = {
    "C1_keywords": "3",
    "C2_filter": "3",          # 키워드 메타 부족 시 STEP 3 재수집
    "C3_auto_build": "6",
    "C4_candidate_folder": "6.7",
    "C5_seo_content": "6.0",
    "C6_set_count_verify": "6.5",
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    recover_step: Optional[str] = None  # 누락 시 권장 단계


async def _http_get(client: httpx.AsyncClient, path: str):
    """JSON (dict 또는 list) 반환. 실패 시 None."""
    try:
        resp = await client.get(f"{dw.BACKEND}{path}", timeout=httpx.Timeout(15.0))
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


async def check_keywords_collected(client: httpx.AsyncClient, target_date: date) -> CheckResult:
    """/api/keywords/dates → [{lookup_date, count}, ...] 형식."""
    data = await _http_get(client, "/api/keywords/dates")
    if data is None:
        return CheckResult("C1_keywords", False, "/api/keywords/dates 호출 실패", "3")
    target_str = str(target_date)
    dates = data if isinstance(data, list) else (data.get("dates") or [])
    for d in dates:
        d_date = d.get("lookup_date") or d.get("date") if isinstance(d, dict) else d
        if d_date == target_str:
            count = d.get("count", 0) if isinstance(d, dict) else 1
            if count > 0:
                return CheckResult("C1_keywords", True, f"키워드 {count}개")
            return CheckResult("C1_keywords", False, "키워드 0개", "3")
    return CheckResult("C1_keywords", False, f"{target_str} 없음 (STEP 3 미실행)", "3")


async def check_auto_filter(client: httpx.AsyncClient, target_date: date) -> CheckResult:
    """auto-filter 재호출 — idempotent. 0건이면 메타데이터(volume/kr_ratio) 누락."""
    body = {
        "competition_max": dw.FILTER_COMPETITION_MAX,
        "kr_ratio_min": dw.FILTER_KR_RATIO_MIN,
        "search_volume_min": dw.FILTER_VOLUME_MIN,
        "date": str(target_date),
        "brand_filter": "all",
    }
    try:
        resp = await client.post(
            f"{dw.BACKEND}/api/keywords/auto-filter", json=body,
            timeout=httpx.Timeout(30.0),
        )
        if resp.status_code != 200:
            return CheckResult("C2_filter", False, f"HTTP {resp.status_code}", "3")
        data = resp.json()
        keywords = data.get("keywords") or []
        total = data.get("total_candidates", 0)
        if not keywords:
            return CheckResult(
                "C2_filter", False,
                f"필터 통과 0개 (전체 후보 {total}). search_volume null 의심",
                "3",
            )
        return CheckResult("C2_filter", True, f"{len(keywords)}개 통과 (전체 후보 {total})")
    except Exception as e:
        return CheckResult("C2_filter", False, f"호출 실패: {e}", "3")


async def check_auto_build(client: httpx.AsyncClient, target_date: date) -> tuple[CheckResult, list[dict]]:
    data = await _http_get(client, f"/api/review/{target_date}")
    if not data:
        return CheckResult("C3_auto_build", False, "/api/review 호출 실패", "6"), []
    if data.get("error") == "no_snapshot":
        return CheckResult("C3_auto_build", False, "auto-build snapshot 없음", "6"), []
    candidates = data.get("candidates") or []
    if not candidates:
        return CheckResult("C3_auto_build", False, "candidates 0개", "6"), []
    return CheckResult("C3_auto_build", True, f"{len(candidates)}개 후보"), candidates


def check_candidate_folder(target_date: date, expected_n: int) -> CheckResult:
    folder = IMAGE_DIR / str(target_date)
    if not folder.exists():
        return CheckResult("C4_candidate_folder", False, f"{folder} 없음", "6.7")
    subs = [p for p in folder.iterdir() if p.is_dir()]
    if not subs:
        return CheckResult("C4_candidate_folder", False, f"{folder} 비어있음", "6.7")
    # expected_n vs 실제 — 70% 이상이면 통과
    coverage = len(subs) / max(expected_n, 1)
    if coverage < 0.7:
        return CheckResult(
            "C4_candidate_folder", False,
            f"폴더 {len(subs)}/{expected_n} (커버리지 {coverage:.0%})",
            "6.7",
        )
    return CheckResult("C4_candidate_folder", True, f"폴더 {len(subs)}/{expected_n}")


def check_seo_content(candidates: list[dict]) -> CheckResult:
    if not candidates:
        return CheckResult("C5_seo_content", False, "candidates 0개", "6.0")
    have = sum(1 for c in candidates if (c.get("qoo10_title_jp") or "").strip())
    coverage = have / len(candidates)
    if coverage < 0.5:
        return CheckResult(
            "C5_seo_content", False,
            f"SEO 콘텐츠 {have}/{len(candidates)} ({coverage:.0%})",
            "6.0",
        )
    return CheckResult("C5_seo_content", True, f"SEO {have}/{len(candidates)}")


def check_set_count_verify(candidates: list[dict]) -> CheckResult:
    """set_count 검증은 마진 ≥ 200% 큐텐 상품만 대상이라 best-effort. 통계만."""
    verified_keys = {"set_count_verified", "set_count_vision_verified", "verified_at"}
    have = sum(
        1 for c in candidates
        if any(c.get(k) for k in verified_keys)
    )
    return CheckResult(
        "C6_set_count_verify", True,  # 항상 통과 (정보용)
        f"검증 표시 {have}/{len(candidates)}",
    )


async def verify(target_date: date) -> tuple[list[CheckResult], dict]:
    """야간 자동화 산출물 검증.

    R-6: AUTOMATION_MODE=keyword_only 면 C3+ (auto-build/폴더/SEO/검증) 는 스킵 —
    해당 단계가 자동화에서 빠진 상태라 부재가 정상.
    """
    mode = (dw.AUTOMATION_MODE or "keyword_only").lower()
    results: list[CheckResult] = []
    async with httpx.AsyncClient() as client:
        # 백엔드 healthcheck
        ping = await _http_get(client, "/api/auth/status")
        if ping is None:
            raise RuntimeError("백엔드 unreachable")

        results.append(await check_keywords_collected(client, target_date))
        results.append(await check_auto_filter(client, target_date))

        if mode == "keyword_only":
            # 자동화는 키워드 RD 까지만 — 이후 단계는 사장님 수동 진행 → 검증 스킵
            pass
        else:
            build_result, candidates = await check_auto_build(client, target_date)
            results.append(build_result)
            expected_n = len(candidates)
            results.append(check_candidate_folder(target_date, expected_n))
            results.append(check_seo_content(candidates))
            results.append(check_set_count_verify(candidates))

    summary = {
        "date": str(target_date),
        "mode": mode,
        "total": len(results),
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok),
        "missing_steps": sorted(set(r.recover_step for r in results if not r.ok and r.recover_step)),
    }
    return results, summary


def _print_human(results: list[CheckResult], summary: dict) -> None:
    mode = summary.get("mode", "?")
    print(f"=== 자동화 검증 ({summary['date']}, mode={mode}) ===")
    for r in results:
        mark = "✓" if r.ok else "✗"
        suffix = f" → STEP {r.recover_step}" if (not r.ok and r.recover_step) else ""
        print(f"  {mark} {r.name}: {r.detail}{suffix}")
    print(f"--- {summary['passed']}/{summary['total']} 통과")
    if mode == "keyword_only":
        print("(keyword_only 모드 — 시트/매칭/이미지 단계는 사장님 수동 진행)")
    if summary["missing_steps"]:
        print(f"권장 복구 단계: {','.join(summary['missing_steps'])}")


def _run_recover(target_date: date, steps: list[str]) -> int:
    cmd = [
        sys.executable,
        str(_THIS_DIR / "recover.py"),
        str(target_date),
        "--only",
        ",".join(steps),
    ]
    print(f"\n[verify] recover.py 자동 호출: {' '.join(cmd)}")
    proc = subprocess.run(cmd)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="야간 자동화 산출물 검증")
    parser.add_argument("date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        help="대상 날짜 (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="결과 JSON 출력")
    parser.add_argument("--recover", action="store_true",
                        help="누락 항목 있으면 recover.py 자동 호출")
    args = parser.parse_args()

    try:
        results, summary = asyncio.run(verify(args.date))
    except RuntimeError as e:
        print(f"[verify] 실패: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "summary": summary,
            "checks": [asdict(r) for r in results],
        }, ensure_ascii=False, indent=2))
    else:
        _print_human(results, summary)

    if summary["failed"] == 0:
        return 0

    if args.recover and summary["missing_steps"]:
        rc = _run_recover(args.date, summary["missing_steps"])
        if rc == 0:
            # 회복 후 재검증 (한 번만)
            print("\n[verify] 회복 후 재검증")
            results2, summary2 = asyncio.run(verify(args.date))
            _print_human(results2, summary2)
            return 0 if summary2["failed"] == 0 else 1
        return rc

    return 1


if __name__ == "__main__":
    sys.exit(main())
