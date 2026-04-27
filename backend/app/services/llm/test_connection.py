"""LLM 백엔드 자가 테스트.

사용:
    cd backend
    python -m app.services.llm.test_connection

수행:
    1) .env 로드 확인
    2) Ollama 서버 핑 + 설정된 ollama 모델로 hello world
    3) Gemini API key 확인 + 설정된 gemini 모델로 hello world
    4) 모두 성공하면 "✅ 모든 LLM 백엔드 정상" 출력

설정된 영역(`*_MODEL`) 만 테스트한다. 한쪽만 쓰는 환경(예: 전부 gemini)에서도 동작.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 프로젝트 루트 sys.path 보장 (python -m 으로 실행 시 backend 가 cwd 일 때만 자동 인식)
_BACKEND = Path(__file__).resolve().parents[3]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND / ".env")

from app.services.llm.router import (  # noqa: E402
    _build_client,
    _parse_spec,
    list_configured_domains,
)


def _color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _ok(s: str) -> str:
    return _color(f"✅ {s}", "32")


def _fail(s: str) -> str:
    return _color(f"❌ {s}", "31")


def _warn(s: str) -> str:
    return _color(f"⚠️  {s}", "33")


async def _hello(spec: str) -> tuple[bool, str]:
    """주어진 모델 사양으로 hello world 호출. (성공여부, 메시지)."""
    try:
        client = _build_client(spec)
    except Exception as e:
        return False, f"클라이언트 생성 실패: {e}"

    try:
        result = await client.chat(
            [{"role": "user", "content": "Say 'hello' in one word."}],
            temperature=0.0,
            max_tokens=20,
        )
        text = (result.text or "").strip().replace("\n", " ")[:60]
        return True, f"{result.latency_ms}ms — {text!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def main() -> int:
    print("=" * 60)
    print(" LLM 백엔드 자가 테스트")
    print("=" * 60)

    domains = list_configured_domains()
    if not domains:
        print(_fail(".env 에 *_MODEL 항목이 하나도 없습니다."))
        return 1

    # provider 별로 1개씩만 테스트 (같은 provider 여러 번 호출 낭비 방지)
    by_provider: dict[str, str] = {}
    for domain, spec in domains.items():
        try:
            provider, _ = _parse_spec(spec)
        except Exception as e:
            print(_fail(f"{domain.upper()}_MODEL={spec!r} 파싱 실패: {e}"))
            return 1
        by_provider.setdefault(provider, spec)

    print(f"\n설정된 영역 ({len(domains)}개):")
    for d, s in sorted(domains.items()):
        print(f"  {d:<20} → {s}")
    print(f"\n테스트할 백엔드 ({len(by_provider)}개): {', '.join(by_provider.keys())}")

    # 사전 점검
    if "ollama" in by_provider:
        print(f"\n[ollama] 서버 URL: {os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}")
    if "gemini" in by_provider:
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if key:
            masked = key[:6] + "..." + key[-4:] if len(key) > 12 else "***"
            print(f"[gemini] API key 감지: {masked}")
        else:
            print(_warn("GEMINI_API_KEY 가 비어있습니다 — gemini 호출 실패 예상"))

    # 호출
    print("\n--- hello world 호출 ---")
    failed: list[str] = []
    for provider, spec in by_provider.items():
        print(f"\n[{provider}] {spec}")
        ok, msg = await _hello(spec)
        if ok:
            print(_ok(msg))
        else:
            print(_fail(msg))
            failed.append(provider)

    print("\n" + "=" * 60)
    if not failed:
        print(_ok("모든 LLM 백엔드 정상"))
        return 0
    print(_fail(f"실패한 백엔드: {', '.join(failed)}"))
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
