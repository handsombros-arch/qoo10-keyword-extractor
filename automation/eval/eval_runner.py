"""LLM 모델 비교 평가 도구.

같은 입력 케이스를 여러 모델에 돌려 정확도 / 지연 / 토큰을 비교, 마크다운 리포트 생성.

사용 (둘 다 허용):
    python -m automation.eval.eval_runner --task category_classification \\
        --models gemini:gemini-2.5-flash,ollama:qwen2.5:7b,ollama:qwen2.5:14b

    python -m automation.eval.eval_runner category_classification \\
        --models gemini:gemini-2.5-flash ollama:qwen2.5:7b ollama:qwen2.5:14b

테스트 케이스 형식 (`automation/eval/test_cases/<task>.jsonl`):
    1) 짧은 형식 (권장):
        {"input": "아누아 어성초 토너", "expected": "03.뷰티&화장품"}
        → prompts/<task>.txt 의 {product_name} 자리에 input 을 넣어 system 메시지 자동 생성.

    2) 긴 형식 (직접 메시지 지정):
        {"input": {"messages": [...], "image_paths": [...] (선택)}, "expected": "..."}
        - input.messages: OpenAI 포맷 메시지 리스트
        - input.image_paths: 비전 평가 시. 있으면 chat_with_image 호출

    공통:
    - expected: 정답 (없으면 정확도 측정 안 하고 응답만 비교)
    - 빈 줄 / "//" 시작 줄은 주석으로 무시

리포트는 `automation/eval/reports/eval_<task>_<YYYYMMDD>.md` 에 저장.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _PROJECT_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND / ".env")

from app.services.llm.router import _build_client, load_prompt  # noqa: E402

_TEST_CASES_DIR = Path(__file__).parent / "test_cases"
_REPORTS_DIR = Path(__file__).parent / "reports"


@dataclass
class CaseResult:
    case_id: int
    expected: str | None
    output: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    error: str | None = None

    @property
    def passed(self) -> bool | None:
        """정답이 있을 때만 True/False, 없으면 None (측정 불가)."""
        if self.expected is None:
            return None
        if self.error is not None:
            return False
        # 라벨 분류 평가는 출력에 정답 라벨이 포함돼 있으면 통과로 본다
        # (LLM이 "분류: 03.뷰티&화장품" 같이 답해도 인정)
        return _normalize(self.expected) in _normalize(self.output)


@dataclass
class ModelResults:
    spec: str
    cases: list[CaseResult] = field(default_factory=list)

    def summary(self) -> dict:
        latencies = [c.latency_ms for c in self.cases if c.error is None]
        scored = [c for c in self.cases if c.passed is not None]
        passed = [c for c in scored if c.passed]
        in_toks = [c.input_tokens for c in self.cases if c.input_tokens is not None]
        out_toks = [c.output_tokens for c in self.cases if c.output_tokens is not None]
        errors = [c for c in self.cases if c.error is not None]

        return {
            "n": len(self.cases),
            "errors": len(errors),
            "scored": len(scored),
            "accuracy": (len(passed) / len(scored)) if scored else None,
            "p50_ms": int(statistics.median(latencies)) if latencies else None,
            "p95_ms": _percentile(latencies, 95) if latencies else None,
            "avg_in_tokens": int(statistics.mean(in_toks)) if in_toks else None,
            "avg_out_tokens": int(statistics.mean(out_toks)) if out_toks else None,
        }


def _normalize(s: str) -> str:
    return (s or "").strip().lower()


def _percentile(data: list[int], p: int) -> int:
    if not data:
        return 0
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return int(s[f] + (s[c] - s[f]) * (k - f))


def _expand_short_input(task: str, raw_input) -> dict:
    """짧은 형식의 input(string) 을 긴 형식(messages list) 으로 확장.

    prompts/<task>.txt 의 {product_name} placeholder 를 input 값으로 치환해 user 메시지로 만든다.
    이미 dict 형식이면 그대로 통과.
    """
    if isinstance(raw_input, dict):
        return raw_input

    if not isinstance(raw_input, str):
        raise ValueError(f"input 은 string 이거나 dict 여야 합니다 (got {type(raw_input).__name__})")

    try:
        template = load_prompt(task)
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"짧은 형식 input 을 쓰려면 prompts/{task}.txt 가 있어야 합니다. {e}"
        )

    # 모든 {xxx} placeholder 를 input 으로 동일 치환.
    # ({product_name}, {keyword} 등 task 마다 다른 placeholder 이름을 쓰지만
    # 짧은 형식은 입력값이 하나라 모두 같은 값으로 채움.)
    import re as _re
    placeholder_re = _re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
    if placeholder_re.search(template):
        content = placeholder_re.sub(raw_input, template)
    else:
        # placeholder 가 하나도 없으면 템플릿 끝에 입력 append
        content = f"{template.rstrip()}\n\n{raw_input}"

    return {"messages": [{"role": "user", "content": content}]}


def _load_cases(task: str) -> list[dict]:
    path = _TEST_CASES_DIR / f"{task}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"테스트 케이스 없음: {path}")
    cases = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no} JSON 파싱 실패: {e}") from e

            raw["input"] = _expand_short_input(task, raw.get("input"))
            cases.append(raw)
    return cases


async def _run_one(spec: str, case: dict) -> CaseResult:
    """한 케이스를 한 모델에 돌리고 결과 반환."""
    client = _build_client(spec)  # 평가는 logger 래핑 없이 직호출 (별도 리포트로 충분)
    inp = case["input"]
    messages = inp.get("messages") or []
    image_paths = inp.get("image_paths") or []
    expected = case.get("expected")

    t0 = time.perf_counter()
    try:
        if image_paths:
            res = await client.chat_with_image(messages, image_paths, temperature=0.0)
        else:
            res = await client.chat(messages, temperature=0.0)
        return CaseResult(
            case_id=case.get("id", 0),
            expected=expected,
            output=res.text or "",
            latency_ms=res.latency_ms,
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
        )
    except Exception as e:
        return CaseResult(
            case_id=case.get("id", 0),
            expected=expected,
            output="",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            input_tokens=None,
            output_tokens=None,
            error=f"{type(e).__name__}: {e}",
        )


async def run_eval(task: str, model_specs: list[str]) -> Path:
    cases = _load_cases(task)
    if not cases:
        raise ValueError(f"테스트 케이스 비어있음: {task}")

    print(f"[eval] {task} — 케이스 {len(cases)}개 × 모델 {len(model_specs)}개")
    all_results: list[ModelResults] = []
    for spec in model_specs:
        print(f"\n[eval] 실행: {spec}")
        mr = ModelResults(spec=spec)
        for i, case in enumerate(cases, 1):
            case = {**case, "id": case.get("id", i)}
            res = await _run_one(spec, case)
            mr.cases.append(res)
            tag = "✓" if res.passed else ("·" if res.passed is None else "✗")
            err = f" [ERR: {res.error}]" if res.error else ""
            print(f"  [{i}/{len(cases)}] {tag} {res.latency_ms}ms{err}")
        all_results.append(mr)

    return _write_report(task, cases, all_results)


def _short_input_label(case: dict) -> str:
    """리포트 표시용 짧은 입력 라벨. messages 의 마지막 user content 첫 200자."""
    msgs = case["input"].get("messages") or []
    last_user = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
    return last_user.split("\n")[-1][:200] if last_user else ""


def _write_report(task: str, cases: list[dict], results: list[ModelResults]) -> Path:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    path = _REPORTS_DIR / f"eval_{task}_{date_str}.md"
    # 같은 날 중복 실행 시 덮어쓰기 대신 시각 suffix
    if path.exists():
        path = _REPORTS_DIR / f"eval_{task}_{date_str}_{datetime.now().strftime('%H%M%S')}.md"

    lines: list[str] = []
    lines.append(f"# Eval Report: {task}")
    lines.append(f"\n실행 시각: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"\n케이스 수: {len(cases)}")

    # 요약 표
    lines.append("\n## 요약\n")
    lines.append("| 모델 | n | 에러 | 정확도 | p50 ms | p95 ms | 평균 입력 토큰 | 평균 출력 토큰 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for mr in results:
        s = mr.summary()
        acc = f"{s['accuracy']*100:.1f}%" if s["accuracy"] is not None else "—"
        lines.append(
            f"| `{mr.spec}` | {s['n']} | {s['errors']} | {acc} | "
            f"{s['p50_ms'] or '—'} | {s['p95_ms'] or '—'} | "
            f"{s['avg_in_tokens'] or '—'} | {s['avg_out_tokens'] or '—'} |"
        )

    # 케이스별 상세
    lines.append("\n## 케이스별 결과\n")
    for i, case in enumerate(cases, 1):
        lines.append(f"\n### Case {i}")
        last_user = _short_input_label(case)
        lines.append(f"\n**입력**: {_md_escape(last_user)}")
        if case["input"].get("image_paths"):
            lines.append(f"\n**이미지**: {', '.join(case['input']['image_paths'])}")
        if case.get("expected") is not None:
            lines.append(f"\n**정답**: `{_md_escape(case['expected'])}`")

        lines.append("\n| 모델 | 출력 | 결과 | 지연 |")
        lines.append("|---|---|---|---|")
        for mr in results:
            cr = mr.cases[i - 1]
            tag = "✅" if cr.passed else ("·" if cr.passed is None else "❌")
            out = cr.error if cr.error else _md_escape(cr.output)[:200]
            lines.append(f"| `{mr.spec}` | {out} | {tag} | {cr.latency_ms}ms |")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[eval] 리포트 저장: {path}")
    return path


def _md_escape(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def _split_models(values: list[str]) -> list[str]:
    """--models 인자가 콤마 또는 스페이스로 구분된 모델 리스트를 평탄화."""
    out: list[str] = []
    for v in values:
        for part in v.split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="LLM 모델 비교 평가")
    p.add_argument(
        "task_pos",
        nargs="?",
        help="태스크명 (test_cases/<task>.jsonl). --task 와 같이 쓸 수도 있음.",
    )
    p.add_argument(
        "--task",
        dest="task_opt",
        help="태스크명 (positional 대신 사용 가능)",
    )
    p.add_argument(
        "--models",
        nargs="+",
        required=True,
        help="비교할 모델 사양. 스페이스 또는 콤마로 구분 "
             "(예: gemini:gemini-2.5-flash,ollama:qwen2.5:14b)",
    )
    args = p.parse_args()

    task = args.task_opt or args.task_pos
    if not task:
        p.error("태스크명이 필요합니다 (positional 또는 --task)")

    models = _split_models(args.models)
    if not models:
        p.error("--models 가 비어있습니다")

    asyncio.run(run_eval(task, models))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
