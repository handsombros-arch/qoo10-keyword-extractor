"""LLM 추론 인프라.

영역별로 다른 모델(Ollama 로컬 / Gemini 클라우드)을 .env 로 라우팅한다.
모든 호출은 자동으로 logs/llm_calls/{date}.jsonl 에 기록된다.

사용 예:
    from app.services.llm import get_client_for

    client = get_client_for("brand")
    result = await client.chat([{"role": "user", "content": "..."}])
    print(result.text)
"""
from .base import ChatResult, LLMClient, Message
from .router import get_client_for, list_configured_domains, load_prompt

__all__ = [
    "ChatResult",
    "LLMClient",
    "Message",
    "get_client_for",
    "list_configured_domains",
    "load_prompt",
]
