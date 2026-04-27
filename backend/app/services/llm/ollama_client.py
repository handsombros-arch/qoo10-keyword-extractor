"""Ollama 로컬 LLM 클라이언트.

OLLAMA_BASE_URL (기본 http://localhost:11434) 의 Ollama 서버를 호출.
- 텍스트: /api/chat
- 비전: /api/chat 의 messages[*].images 에 base64 인코딩 첨부 (qwen2.5-vl, llava 등 비전 모델 필요)

ollama 파이썬 패키지 사용 (비공식 의존성 회피 + async 호환 위해 httpx 직접 호출도 가능하지만
ollama 0.4+ 의 AsyncClient 가 안정적이라 그것 사용).
"""
from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path

from .base import ChatResult, LLMClient, Message

logger = logging.getLogger(__name__)


class OllamaClient(LLMClient):
    """Ollama 로컬 서버 클라이언트."""

    def __init__(self, model: str, base_url: str | None = None):
        # name 형식: "ollama:qwen2.5:14b"  (provider:model 식별자)
        self.name = f"ollama:{model}"
        self.model = model
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        # 비전 지원은 모델 이름으로 추정. 새 모델 추가 시 키워드 추가.
        self.supports_vision = any(
            tok in model.lower()
            for tok in ("vl", "vision", "llava", "minicpm-v", "moondream", "gemma3")
        )

    def _client(self):
        try:
            from ollama import AsyncClient
        except ImportError as e:
            raise RuntimeError(
                "ollama 패키지 미설치. `pip install ollama` 후 다시 시도하세요."
            ) from e
        return AsyncClient(host=self.base_url)

    async def chat(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResult:
        client = self._client()
        options: dict = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        kwargs = {
            "model": self.model,
            "messages": list(messages),
            "options": options,
        }
        if json_mode:
            kwargs["format"] = "json"

        t0 = time.perf_counter()
        resp = await client.chat(**kwargs)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        # ollama 0.4+: ChatResponse 객체. dict 호환.
        message = resp["message"] if isinstance(resp, dict) else resp.message
        text = message["content"] if isinstance(message, dict) else message.content

        prompt_eval = (
            resp.get("prompt_eval_count") if isinstance(resp, dict)
            else getattr(resp, "prompt_eval_count", None)
        )
        eval_count = (
            resp.get("eval_count") if isinstance(resp, dict)
            else getattr(resp, "eval_count", None)
        )

        return ChatResult(
            text=text,
            model=self.name,
            input_tokens=prompt_eval,
            output_tokens=eval_count,
            latency_ms=latency_ms,
            raw=resp if isinstance(resp, dict) else {},
        )

    async def chat_with_image(
        self,
        messages: list[Message],
        image_paths: list[str],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResult:
        if not self.supports_vision:
            raise NotImplementedError(
                f"{self.name} 는 비전 미지원 모델로 추정됩니다 "
                f"(qwen2.5-vl, llava 등 비전 모델을 사용하세요)."
            )

        # 마지막 user 메시지에 images 첨부 (Ollama 규약).
        msgs = [dict(m) for m in messages]
        encoded = [_b64(p) for p in image_paths]
        attached = False
        for m in reversed(msgs):
            if m.get("role") == "user":
                m["images"] = encoded
                attached = True
                break
        if not attached:
            msgs.append({"role": "user", "content": "", "images": encoded})

        client = self._client()
        options: dict = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        kwargs = {"model": self.model, "messages": msgs, "options": options}
        if json_mode:
            kwargs["format"] = "json"

        t0 = time.perf_counter()
        resp = await client.chat(**kwargs)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        message = resp["message"] if isinstance(resp, dict) else resp.message
        text = message["content"] if isinstance(message, dict) else message.content
        prompt_eval = (
            resp.get("prompt_eval_count") if isinstance(resp, dict)
            else getattr(resp, "prompt_eval_count", None)
        )
        eval_count = (
            resp.get("eval_count") if isinstance(resp, dict)
            else getattr(resp, "eval_count", None)
        )

        return ChatResult(
            text=text,
            model=self.name,
            input_tokens=prompt_eval,
            output_tokens=eval_count,
            latency_ms=latency_ms,
            raw=resp if isinstance(resp, dict) else {},
        )


def _b64(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("ascii")
