"""LLM 클라이언트 추상 인터페이스.

모든 백엔드(Ollama, Gemini, ...)는 LLMClient 를 상속해서
chat / chat_with_image 두 메서드를 구현한다.

메시지 포맷은 OpenAI 호환:
    {"role": "system" | "user" | "assistant", "content": "..."}
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypedDict


class Message(TypedDict, total=False):
    role: str       # "system" | "user" | "assistant"
    content: str


@dataclass
class ChatResult:
    """LLM 호출 결과.

    text: 응답 텍스트
    model: "ollama:qwen2.5:14b" 같은 식별자
    input_tokens / output_tokens: 모를 경우 None
    latency_ms: 호출~응답까지 밀리초
    raw: 디버깅용 원본 응답 dict (로그에는 안 기록)
    """
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    """LLM 백엔드 공통 인터페이스."""

    name: str               # "ollama:qwen2.5:14b" 같은 식별자
    supports_vision: bool   # chat_with_image 지원 여부

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """텍스트 채팅. json_mode=True 면 백엔드가 JSON 응답을 강제."""
        raise NotImplementedError

    @abstractmethod
    async def chat_with_image(
        self,
        messages: list[Message],
        image_paths: list[str],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """이미지 + 텍스트 멀티모달. 비전 미지원 백엔드는 NotImplementedError."""
        raise NotImplementedError
