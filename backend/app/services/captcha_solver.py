"""captcha 자동 풀이 — 비용 0 cascade (EasyOCR → vision LLM) + 옵션 2Captcha API.

흐름:
    1) **로컬 EasyOCR** (비용 0) — 단순 영문/숫자 captcha. 정확도 ~60%
    2) **로컬 vision LLM** (비용 0) — qwen2.5vl 등으로 텍스트 추론. 정확도 ~40%
    3) **2Captcha API** (선택, ~$1/1000건) — 인간 풀이 정확도 ~95%
    4) 모두 실패 + CDP attach 면 사장님 GUI 직접 풀이 (caller 가 처리)

env:
    CAPTCHA_LOCAL_OCR=1                     (기본 1, EasyOCR 사용)
    CAPTCHA_LOCAL_VISION_LLM=0              (기본 0, vision LLM 시도. 비싸서 off)
    CAPTCHA_API_KEY=<2captcha api key>     (선택, 비어있으면 외부 API 비활성)
    CAPTCHA_TIMEOUT_SEC=120

사용:
    from app.services.captcha_solver import solve_image_captcha
    text = await solve_image_captcha(image_bytes)  # cascade 자동 시도
    if text:
        await page.fill('#captcha_input', text)
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://2captcha.com"


def _api_key() -> str | None:
    return (os.getenv("CAPTCHA_API_KEY") or "").strip() or None


def _timeout() -> int:
    try:
        return int(os.getenv("CAPTCHA_TIMEOUT_SEC") or "120")
    except ValueError:
        return 120


async def _solve_local_easyocr(image_bytes: bytes, *, expected_len: int = 6) -> str | None:
    """EasyOCR 로 captcha 풀이. 한글/영문/숫자 인식.

    NAVER 보안문자는 보통 5~6자리 영문 대문자/소문자 + 숫자.
    OCR 결과에서 영숫자 토큰만 추출 → 가장 길고 expected_len 에 가까운 것.
    """
    if (os.getenv("CAPTCHA_LOCAL_OCR") or "1") != "1":
        return None
    try:
        from app.services.ocr import ocr_image_async
    except ImportError:
        return None
    try:
        # 1차 — 원본
        text = await ocr_image_async(image_bytes)
        if not text:
            return None
        # 영숫자 토큰만 추출 (공백/특수문자 제거)
        tokens = re.findall(r"[A-Za-z0-9]+", text)
        if not tokens:
            return None
        # 가장 길고 expected_len 에 가까운 것
        tokens.sort(key=lambda t: (abs(len(t) - expected_len), -len(t)))
        cand = tokens[0]
        if 3 <= len(cand) <= 12:
            logger.info(f"[captcha/ocr] EasyOCR 풀이: {cand!r} (raw={text[:40]!r})")
            return cand
    except Exception as e:
        logger.debug(f"[captcha/ocr] 실패: {e}")
    return None


async def _solve_local_vision_llm(image_bytes: bytes) -> str | None:
    """로컬 vision LLM 으로 captcha 풀이 (비용 0). 정확도 낮으니 default off."""
    if (os.getenv("CAPTCHA_LOCAL_VISION_LLM") or "0") != "1":
        return None
    try:
        from app.services.llm.router import _build_client
    except ImportError:
        return None
    spec = (os.getenv("VISION_MODEL") or "ollama:qwen2.5vl:7b").strip()
    try:
        client = _build_client(spec)
    except Exception:
        return None

    # 이미지 임시 파일 저장
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(image_bytes); tmp.close()
    try:
        prompt = (
            "이 이미지의 captcha 텍스트만 정확히 출력하세요. "
            "다른 설명 없이 captcha 의 글자/숫자만 한 줄로. "
            "공백 없이 영문 대소문자/숫자만."
        )
        result = await client.chat_with_image(
            [{"role": "user", "content": prompt}],
            [tmp.name],
            temperature=0.0,
            max_tokens=64,
        )
        text = (result.text or "").strip()
        m = re.findall(r"[A-Za-z0-9]+", text)
        if m:
            cand = max(m, key=len)
            if 3 <= len(cand) <= 12:
                logger.info(f"[captcha/vlm] vision LLM 풀이: {cand!r}")
                return cand
    except Exception as e:
        logger.debug(f"[captcha/vlm] 실패: {e}")
    finally:
        try:
            from pathlib import Path as _P
            _P(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass
    return None


async def solve_image_captcha(image_bytes: bytes, *, hint: str = "") -> str | None:
    """이미지 captcha 풀이 — cascade 시도. 비용 0 우선.

    1) EasyOCR (비용 0, ~60% 정확도)
    2) 로컬 vision LLM (비용 0, ~40% 정확도, default off)
    3) 2Captcha API (~$1/1000건, ~95% 정확도)
    """
    if not image_bytes or len(image_bytes) < 100:
        return None

    # 1) EasyOCR
    text = await _solve_local_easyocr(image_bytes)
    if text:
        return text

    # 2) 로컬 vision LLM
    text = await _solve_local_vision_llm(image_bytes)
    if text:
        return text

    # 3) 2Captcha API (옵션)
    api_key = _api_key()
    if not api_key:
        logger.debug("[captcha] 로컬 풀이 모두 실패 + API key 없음 — return None")
        return None

    b64 = base64.b64encode(image_bytes).decode("ascii")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 1) 업로드
            data = {
                "key": api_key,
                "method": "base64",
                "body": b64,
                "json": "1",
            }
            if hint:
                data["textinstructions"] = hint
            r = await client.post(f"{_API_URL}/in.php", data=data)
            r.raise_for_status()
            resp = r.json()
            if str(resp.get("status")) != "1":
                logger.warning(f"[captcha] 업로드 실패: {resp}")
                return None
            captcha_id = resp.get("request")
            if not captcha_id:
                return None

            # 2) 폴링 — 5초 간격, 최대 timeout
            deadline = asyncio.get_event_loop().time() + _timeout()
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(5)
                r2 = await client.get(
                    f"{_API_URL}/res.php",
                    params={"key": api_key, "action": "get", "id": captcha_id, "json": "1"},
                )
                r2.raise_for_status()
                d2 = r2.json()
                status = str(d2.get("status"))
                req = d2.get("request") or ""
                if status == "1":
                    text = req.strip()
                    logger.info(f"[captcha] 풀이 OK (id={captcha_id}, len={len(text)})")
                    return text
                if status == "0" and req == "CAPCHA_NOT_READY":
                    continue
                # 그 외 — 실패
                logger.warning(f"[captcha] 풀이 실패: {d2}")
                return None
            logger.warning(f"[captcha] 풀이 타임아웃 ({_timeout()}초)")
            return None
    except Exception as e:
        logger.warning(f"[captcha] API 호출 실패: {type(e).__name__}: {e}")
        return None


async def solve_recaptcha_v2(*, site_key: str, page_url: str) -> str | None:
    """reCAPTCHA v2 풀이 — site_key + page_url 로 g-recaptcha-response 토큰 얻음.

    사용:
        token = await solve_recaptcha_v2(site_key="6Lc...", page_url=page.url)
        await page.evaluate(f'document.getElementById("g-recaptcha-response").innerHTML="{token}"')
    """
    api_key = _api_key()
    if not api_key or not site_key or not page_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{_API_URL}/in.php", data={
                "key": api_key,
                "method": "userrecaptcha",
                "googlekey": site_key,
                "pageurl": page_url,
                "json": "1",
            })
            r.raise_for_status()
            resp = r.json()
            if str(resp.get("status")) != "1":
                logger.warning(f"[captcha/recaptcha] 업로드 실패: {resp}")
                return None
            captcha_id = resp.get("request")

            deadline = asyncio.get_event_loop().time() + _timeout()
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(7)
                r2 = await client.get(
                    f"{_API_URL}/res.php",
                    params={"key": api_key, "action": "get", "id": captcha_id, "json": "1"},
                )
                d2 = r2.json()
                if str(d2.get("status")) == "1":
                    return (d2.get("request") or "").strip()
                if str(d2.get("status")) == "0" and (d2.get("request") or "") == "CAPCHA_NOT_READY":
                    continue
                logger.warning(f"[captcha/recaptcha] 실패: {d2}")
                return None
    except Exception as e:
        logger.warning(f"[captcha/recaptcha] API 실패: {e}")
    return None


__all__ = ["solve_image_captcha", "solve_recaptcha_v2"]
