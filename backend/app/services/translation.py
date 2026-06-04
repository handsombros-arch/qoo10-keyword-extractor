"""번역 — Papago(NCP, 유료) 우선 + Google(무료) 폴백 + 캐시.

- 크리덴셜(PAPAGO_CLIENT_ID/SECRET in .env) 있으면 Papago, 없으면 Google 자동 폴백.
- TranslationCache 로 같은 원문 재번역 방지 → 호출/비용 최소화 (no-API 로드맵 정합).
"""
import asyncio

import httpx

from app.config import settings

GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"


async def translate_google(text: str, source: str = "ja", target: str = "ko") -> str:
    """구글 번역 무료 endpoint. API 키 불필요. (폴백용)"""
    if not text:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                GOOGLE_TRANSLATE_URL,
                params={"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and data[0]:
                    return "".join(seg[0] for seg in data[0] if seg and seg[0])
    except Exception:
        pass
    return text


async def _papago_api(text: str, source: str, target: str) -> str | None:
    """Papago NCP NMT. 크리덴셜 없거나 실패 시 None → 호출측이 Google 폴백."""
    cid = getattr(settings, "PAPAGO_CLIENT_ID", "")
    csec = getattr(settings, "PAPAGO_CLIENT_SECRET", "")
    if not cid or not csec:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                settings.PAPAGO_API_URL,
                headers={
                    "X-NCP-APIGW-API-KEY-ID": cid,
                    "X-NCP-APIGW-API-KEY": csec,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"source": source, "target": target, "text": text},
            )
            if resp.status_code == 200:
                return resp.json()["message"]["result"]["translatedText"]
            # 401/403/429 등은 None 반환 → Google 폴백
    except Exception:
        return None
    return None


async def _cache_get(text: str, src: str, tgt: str) -> str | None:
    try:
        from app.db.connection import async_session
        from app.db.models import TranslationCache
        async with async_session() as session:
            row = await session.get(TranslationCache, (text, src, tgt))
            return row.translated if row else None
    except Exception:
        return None


async def _cache_put(text: str, src: str, tgt: str, translated: str, model: str) -> None:
    try:
        from app.db.connection import async_session
        from app.db.models import TranslationCache
        async with async_session() as session:
            session.add(TranslationCache(
                source_text=text, source_lang=src, target_lang=tgt,
                translated=translated, model=model,
            ))
            await session.commit()
    except Exception:
        pass  # 중복 PK 등은 무시


async def translate_text(text: str, source: str = "ja", target: str = "ko") -> str:
    """캐시 → Papago(크리덴셜 시) → Google 폴백 → 캐시 저장."""
    if not text:
        return ""
    cached = await _cache_get(text, source, target)
    if cached is not None:
        return cached
    out = await _papago_api(text, source, target)
    model = "papago"
    if not out:
        out = await translate_google(text, source, target)
        model = "google"
    if out and out != text:
        await _cache_put(text, source, target, out, model)
    return out or text


async def translate_batch(
    texts: list[str], source: str = "ja", target: str = "ko", concurrency: int = 5
) -> list[str]:
    """여러 문자열 동시 번역 (각 항목 캐시/Papago/Google 거침)."""
    sem = asyncio.Semaphore(concurrency)

    async def one(t: str) -> str:
        async with sem:
            return await translate_text(t, source, target)

    return await asyncio.gather(*(one(t) for t in texts))


# 하위 호환 별칭 — 이제 캐시+Papago+Google폴백 단일 경로
translate_papago = translate_text
