"""번역 — Papago 웹(무료, 원본 방식) 우선 + Google 폴백 + 캐시.

- translate_batch(키워드 경로): 캐시 → **papago.naver.com 실Chrome 배치** → 구글 폴백 → 캐시.
  원본 키워드 추출기와 동일하게 무료로 브랜드 음역까지 정확(마스크/제모/아스타리프트 등).
  브라우저 미가용 시 자동으로 구글로 폴백(깨지지 않음).
- translate_text(단건): 캐시 → Papago NCP API(크리덴셜 시) → 구글. (recommendations/related 등)
- TranslationCache 로 재번역 방지 → 호출 최소화 (no-API 로드맵 정합).
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


async def _papago_web_batch(texts: list[str], source: str, target: str) -> list[str | None] | None:
    """papago.naver.com(실 Chrome) 배치 번역 — 원본 키워드 추출기와 동일 무료 고품질 경로.
    브라우저 미가용/실패 시 None → 호출측 구글 폴백. 청크별 실패는 해당 칸만 None."""
    try:
        from app.browser.manager import browser_manager
        from app.scrapers.papago_web import papago_translate_batch
    except Exception:
        return None
    try:
        page = await browser_manager.new_page()
    except Exception:
        return None  # 브라우저 없음 → 구글 폴백
    try:
        out: list[str | None] = []
        CHUNK = 20
        for s in range(0, len(texts), CHUNK):
            chunk = texts[s:s + CHUNK]
            r = await papago_translate_batch(page, chunk, source, target)
            if r is None or len(r) != len(chunk):
                out.extend([None] * len(chunk))
            else:
                out.extend(v or None for v in r)
        return out
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def translate_batch(
    texts: list[str], source: str = "ja", target: str = "ko", concurrency: int = 5
) -> list[str]:
    """캐시 → Papago 웹(배치) → 구글 폴백 → 캐시. 브라우저 없으면 캐시→구글.

    원본 키워드 추출기처럼 papago.naver.com 을 구동해 브랜드 음역까지 정확히.
    """
    results: list = [None] * len(texts)
    uncached: list[int] = []
    for i, t in enumerate(texts):
        if not t:
            results[i] = ""
            continue
        c = await _cache_get(t, source, target)
        if c is not None:
            results[i] = c
        else:
            uncached.append(i)

    if uncached:
        unc_texts = [texts[i] for i in uncached]
        papago = await _papago_web_batch(unc_texts, source, target)
        for j, i in enumerate(uncached):
            v = papago[j] if papago and j < len(papago) else None
            if v:
                results[i] = v
                await _cache_put(texts[i], source, target, v, "papago_web")
        # papago 실패/빈값 → 구글 폴백
        for i in uncached:
            if results[i] is None:
                v = await translate_google(texts[i], source, target)
                results[i] = v
                if v and v != texts[i]:
                    await _cache_put(texts[i], source, target, v, "google")

    return results


# 하위 호환 별칭 — 이제 캐시+Papago+Google폴백 단일 경로
translate_papago = translate_text
