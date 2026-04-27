"""영역별 모델 라우터.

.env 의 `<DOMAIN>_MODEL` 키를 `provider:model` 형식으로 파싱해 클라이언트를 만든다.

지원 형식:
    ollama:qwen2.5:14b      → OllamaClient(model="qwen2.5:14b")
    gemini:gemini-2.5-flash → GeminiClient(model="gemini-2.5-flash")

영역명 → env 키 매핑:
    "category"   → CATEGORY_MODEL
    "brand"      → BRAND_MODEL
    "set_count"  → SET_COUNT_MODEL
    "vision"     → VISION_MODEL
    ...

새 영역 추가 시: .env 에 `<UPPER>_MODEL=...` 한 줄 + prompts/<lower>.txt 만들면 끝.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from .base import LLMClient
from .gemini_client import GeminiClient
from .logger import LoggingClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _parse_spec(spec: str) -> tuple[str, str]:
    """'ollama:qwen2.5:14b' → ('ollama', 'qwen2.5:14b')

    provider 는 첫 번째 ':' 까지, model 은 나머지 전부 (모델명에 ':' 가 들어가는 ollama 태그 대응).
    """
    spec = (spec or "").strip()
    if ":" not in spec:
        raise ValueError(
            f"잘못된 모델 사양: {spec!r}. 'provider:model' 형식이어야 합니다 "
            f"(예: 'ollama:qwen2.5:14b', 'gemini:gemini-2.5-flash')."
        )
    provider, model = spec.split(":", 1)
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        raise ValueError(f"잘못된 모델 사양: {spec!r}")
    return provider, model


def _build_client(spec: str) -> LLMClient:
    provider, model = _parse_spec(spec)
    if provider == "ollama":
        return OllamaClient(model)
    if provider == "gemini":
        return GeminiClient(model)
    raise ValueError(f"지원하지 않는 provider: {provider!r} (ollama|gemini)")


def _env_key(domain: str) -> str:
    return f"{domain.upper()}_MODEL"


@lru_cache(maxsize=32)
def get_client_for(domain: str) -> LLMClient:
    """영역명에 해당하는 LLM 클라이언트 반환. 자동 로깅 래핑.

    캐시되므로 같은 영역은 같은 인스턴스 재사용.
    .env 변경 후 반영하려면 `get_client_for.cache_clear()` 호출.
    """
    key = _env_key(domain)
    spec = os.getenv(key, "").strip()
    if not spec:
        raise RuntimeError(
            f"영역 {domain!r} 의 모델이 .env 에 설정되지 않았습니다 ({key} 가 비어있음)."
        )
    inner = _build_client(spec)
    return LoggingClient(inner, domain=domain)


def list_configured_domains() -> dict[str, str]:
    """현재 .env 에 설정된 모든 `*_MODEL` 항목을 영역명: 사양 으로 반환."""
    out: dict[str, str] = {}
    for k, v in os.environ.items():
        if k.endswith("_MODEL") and v.strip():
            domain = k[:-len("_MODEL")].lower()
            out[domain] = v.strip()
    return out


def load_prompt(name: str) -> str:
    """prompts/<name>.txt 의 내용 반환. UTF-8."""
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"프롬프트 파일 없음: {path}")
    return path.read_text(encoding="utf-8")
