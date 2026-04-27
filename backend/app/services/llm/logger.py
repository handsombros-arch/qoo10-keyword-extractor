"""LLM 호출 로그 (JSONL).

LLM_LOG_ENABLED=true 면 logs/llm_calls/{YYYY-MM-DD}.jsonl 에 한 줄씩 append.
이미지는 경로만 기록 (용량 폭발 방지).

logs/llm_calls/ 는 .gitignore 처리 (이미 logs/ 로 cover 됨).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from .base import ChatResult, LLMClient, Message

logger = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = "logs/llm_calls"


def _is_enabled() -> bool:
    return os.getenv("LLM_LOG_ENABLED", "true").lower() in ("1", "true", "yes")


def _log_dir() -> Path:
    """프로젝트 루트 기준 로그 디렉토리. backend/ 의 부모를 루트로 본다."""
    raw = os.getenv("LLM_LOG_DIR", _DEFAULT_LOG_DIR)
    p = Path(raw)
    if not p.is_absolute():
        # backend/app/services/llm/logger.py → 4단계 위가 프로젝트 루트
        project_root = Path(__file__).resolve().parents[4]
        p = project_root / p
    return p


def _today_path() -> Path:
    d = _log_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"


def _trim(obj: Any, max_len: int = 4000) -> Any:
    """큰 텍스트는 잘라서 저장. JSON 직렬화 가능한 형태 보장."""
    if isinstance(obj, str):
        return obj if len(obj) <= max_len else obj[:max_len] + f"...[truncated {len(obj) - max_len}]"
    if isinstance(obj, list):
        return [_trim(x, max_len) for x in obj]
    if isinstance(obj, dict):
        return {k: _trim(v, max_len) for k, v in obj.items()}
    return obj


def write_call_log(
    *,
    domain: str,
    model: str,
    messages: list[Message],
    image_paths: list[str] | None,
    result: ChatResult | None,
    error: str | None,
) -> None:
    """한 호출을 JSONL 한 줄로 기록. 실패해도 호출 흐름은 막지 않음."""
    if not _is_enabled():
        return

    record = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "domain": domain,
        "model": model,
        "input": {
            "messages": _trim(messages),
            "image_paths": list(image_paths) if image_paths else [],
        },
        "output": _trim(result.text) if result else None,
        "input_tokens": result.input_tokens if result else None,
        "output_tokens": result.output_tokens if result else None,
        "latency_ms": result.latency_ms if result else None,
        "ok": error is None,
        "error": error,
    }

    try:
        path = _today_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[llm.logger] 로그 기록 실패 (무시): {e}")


class LoggingClient(LLMClient):
    """모든 호출을 자동 로깅하는 래퍼.

    router 가 client 인스턴스를 항상 이걸로 감싸 반환 → 호출부는 로깅을 신경 안 써도 됨.
    """

    def __init__(self, inner: LLMClient, domain: str):
        self._inner = inner
        self._domain = domain
        self.name = inner.name
        self.supports_vision = inner.supports_vision

    async def chat(self, messages, *, json_mode=False, temperature=0.0, max_tokens=None):
        result, err = None, None
        try:
            result = await self._inner.chat(
                messages, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens,
            )
            return result
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            raise
        finally:
            write_call_log(
                domain=self._domain, model=self.name,
                messages=messages, image_paths=None,
                result=result, error=err,
            )

    async def chat_with_image(
        self, messages, image_paths, *, json_mode=False, temperature=0.0, max_tokens=None,
    ):
        result, err = None, None
        try:
            result = await self._inner.chat_with_image(
                messages, image_paths,
                json_mode=json_mode, temperature=temperature, max_tokens=max_tokens,
            )
            return result
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            raise
        finally:
            write_call_log(
                domain=self._domain, model=self.name,
                messages=messages, image_paths=image_paths,
                result=result, error=err,
            )
