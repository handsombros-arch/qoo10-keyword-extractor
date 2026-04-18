import asyncio
import httpx


GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"


async def translate_papago(text: str, source: str = "ja", target: str = "ko") -> str:
    """Google 무료 비공식 번역 endpoint 사용. (이름은 호환 위해 유지)"""
    if not text:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                GOOGLE_TRANSLATE_URL,
                params={
                    "client": "gtx",
                    "sl": source,
                    "tl": target,
                    "dt": "t",
                    "q": text,
                },
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and data[0]:
                    return "".join(seg[0] for seg in data[0] if seg and seg[0])
    except Exception:
        pass
    return text


async def translate_batch(
    texts: list[str], source: str = "ja", target: str = "ko", concurrency: int = 5
) -> list[str]:
    """여러 문자열을 동시에 번역."""
    sem = asyncio.Semaphore(concurrency)

    async def one(t: str) -> str:
        async with sem:
            return await translate_papago(t, source, target)

    return await asyncio.gather(*(one(t) for t in texts))
