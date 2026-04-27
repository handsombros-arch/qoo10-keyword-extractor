"""Google Gemini API 클라이언트 (텍스트 + 비전).

키 풀 + 자동 페일오버:
    - GEMINI_API_KEYS (콤마구분, 우선) 또는 GEMINI_API_KEY (단일, fallback)
    - 호출마다 round-robin 으로 다음 키 선택
    - 429 ResourceExhausted (quota 초과) 시 자동으로 다음 키 retry
    - 모든 키 소진 시 마지막 에러 raise (caller 에서 인지 가능)

google-generativeai SDK 가 module-level config 를 쓰므로 호출 직렬화 (Lock).
동시 호출 X — category 분류 같이 순차 진행되는 task 에 적합.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import time
from pathlib import Path

from .base import ChatResult, LLMClient, Message

logger = logging.getLogger(__name__)


# ─── 키 풀 ──────────────────────────────────────────────

class _KeyPool:
    """GEMINI_API_KEYS (콤마구분) 또는 GEMINI_API_KEY 에서 키 로드.

    next() 는 round-robin. mark_exhausted(key) 는 일시 차단 (retry 시 스킵).
    """
    def __init__(self):
        self._keys: list[str] = []
        self._idx = 0
        self._exhausted: set[str] = set()
        self._loaded = False

    def _load(self) -> None:
        many = os.getenv("GEMINI_API_KEYS", "").strip()
        if many:
            keys = [k.strip() for k in many.split(",") if k.strip()]
        else:
            single = os.getenv("GEMINI_API_KEY", "").strip()
            keys = [single] if single else []
        self._keys = keys
        self._idx = 0
        self._exhausted.clear()
        self._loaded = True
        if keys:
            logger.info(f"[gemini] 키 풀 로드 — 총 {len(keys)}개")

    def all_keys(self) -> list[str]:
        if not self._loaded:
            self._load()
        return list(self._keys)

    def next_key(self) -> str | None:
        """다음 사용 가능한 키 반환. 모두 소진이면 None."""
        if not self._loaded:
            self._load()
        if not self._keys:
            return None
        for _ in range(len(self._keys)):
            key = self._keys[self._idx % len(self._keys)]
            self._idx += 1
            if key not in self._exhausted:
                return key
        return None

    def mark_exhausted(self, key: str) -> None:
        self._exhausted.add(key)
        logger.warning(
            f"[gemini] 키 소진 표시 ({key[:6]}...{key[-4:]}). "
            f"남은 키: {len(self._keys) - len(self._exhausted)}/{len(self._keys)}"
        )


_pool = _KeyPool()
_CONFIG_LOCK = asyncio.Lock()  # genai.configure 가 모듈 전역이라 직렬화


def _to_gemini_contents(messages: list[Message]) -> tuple[str | None, list[dict]]:
    """OpenAI 포맷 messages → Gemini 포맷 (system_instruction, contents).

    Gemini 는 role 이 'user' / 'model' 만 허용. system 은 system_instruction 으로 분리.
    """
    system_parts: list[str] = []
    contents: list[dict] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            system_parts.append(content)
            continue
        gemini_role = "user" if role == "user" else "model"
        contents.append({"role": gemini_role, "parts": [{"text": content}]})

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


def _is_quota_error(e: Exception) -> bool:
    """ResourceExhausted (429) 또는 기타 quota 관련 에러 식별."""
    name = type(e).__name__
    if name == "ResourceExhausted":
        return True
    msg = str(e).lower()
    return "429" in msg or "quota" in msg or "resourceexhausted" in msg


class GeminiClient(LLMClient):
    """Gemini API 클라이언트 — 키 풀 + 자동 페일오버."""

    def __init__(self, model: str):
        # name: "gemini:gemini-2.5-flash"
        self.name = f"gemini:{model}"
        self.model = model
        # Gemini 모든 모델은 멀티모달 지원 (2.5 Flash 포함)
        self.supports_vision = True

    def _make_model(self, system_instruction: str | None, json_mode: bool, temperature: float, max_tokens: int | None):
        import google.generativeai as genai

        generation_config: dict = {"temperature": temperature}
        if max_tokens is not None:
            generation_config["max_output_tokens"] = max_tokens
        if json_mode:
            generation_config["response_mime_type"] = "application/json"

        return genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system_instruction,
            generation_config=generation_config,
        )

    async def _call_with_failover(
        self,
        contents: list[dict],
        system_instruction: str | None,
        json_mode: bool,
        temperature: float,
        max_tokens: int | None,
    ) -> tuple[object, int]:
        """키 풀 순회하며 호출. 429 면 다음 키. 모든 키 소진 시 마지막 에러 raise.

        반환: (resp, latency_ms)
        """
        try:
            import google.generativeai as genai  # noqa: F401  (configure 호출 위해)
        except ImportError as e:
            raise RuntimeError(
                "google-generativeai 미설치. `pip install google-generativeai` 후 재시도."
            ) from e

        keys = _pool.all_keys()
        if not keys:
            raise RuntimeError(
                "GEMINI 키 없음. .env 에 GEMINI_API_KEY 또는 GEMINI_API_KEYS (콤마구분) 설정."
            )

        last_err: Exception | None = None
        # 최대 키 수 만큼 시도 (각 키 1회)
        for attempt in range(len(keys)):
            key = _pool.next_key()
            if key is None:
                break  # 모두 소진

            async with _CONFIG_LOCK:
                import google.generativeai as genai
                genai.configure(api_key=key)
                model = self._make_model(system_instruction, json_mode, temperature, max_tokens)
                t0 = time.perf_counter()
                try:
                    resp = await asyncio.to_thread(model.generate_content, contents)
                    latency_ms = int((time.perf_counter() - t0) * 1000)
                    return resp, latency_ms
                except Exception as e:
                    last_err = e
                    if _is_quota_error(e):
                        _pool.mark_exhausted(key)
                        logger.warning(
                            f"[gemini] 429 quota — 키 페일오버 "
                            f"(시도 {attempt+1}/{len(keys)}): {type(e).__name__}"
                        )
                        continue
                    # quota 외 다른 에러는 즉시 raise (재시도 무의미)
                    raise

        # 모든 키 소진
        if last_err:
            raise last_err
        raise RuntimeError("[gemini] 사용 가능한 키 없음 (전부 소진)")

    async def chat(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatResult:
        system_instruction, contents = _to_gemini_contents(messages)
        resp, latency_ms = await self._call_with_failover(
            contents, system_instruction, json_mode, temperature, max_tokens,
        )
        text = _extract_text(resp)
        usage = getattr(resp, "usage_metadata", None)
        return ChatResult(
            text=text,
            model=self.name,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            latency_ms=latency_ms,
            raw={},
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
        system_instruction, contents = _to_gemini_contents(messages)

        # 마지막 user contents 에 이미지 part 추가
        image_parts = [_image_part(p) for p in image_paths]
        if contents and contents[-1]["role"] == "user":
            contents[-1]["parts"].extend(image_parts)
        else:
            contents.append({"role": "user", "parts": image_parts})

        resp, latency_ms = await self._call_with_failover(
            contents, system_instruction, json_mode, temperature, max_tokens,
        )
        text = _extract_text(resp)
        usage = getattr(resp, "usage_metadata", None)
        return ChatResult(
            text=text,
            model=self.name,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            latency_ms=latency_ms,
            raw={},
        )


def _image_part(path: str) -> dict:
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = "image/jpeg"
    data = Path(path).read_bytes()
    return {"inline_data": {"mime_type": mime, "data": data}}


def _extract_text(resp) -> str:
    """Gemini 응답에서 텍스트 안전하게 추출."""
    try:
        return resp.text or ""
    except Exception:
        # safety filter 등으로 .text 가 막히는 경우 candidates 에서 직접 긁기
        try:
            parts = resp.candidates[0].content.parts
            return "".join(getattr(p, "text", "") for p in parts)
        except Exception:
            return ""
