"""실시간 환율 조회 — 1 통화단위당 원화 (예: JPY → 1엔 = 약 9.x원).

- 반환 단위 = **1단위당 원화** (per-yen). Dunamu basePrice 는 JPY가 100엔당(~927)이라
  currencyUnit 로 나눠 1엔당(~9.27)으로 정규화한다.
  (호출처 price_compare 는 `>20 이면 /100` 가드가 있어 어느 단위든 안전.)
- **하루 1회 캐시** (같은 날 재호출은 네트워크 안 탐).
- Dunamu 실패 시 open.er-api.com 폴백 → 그것도 실패면 직전 캐시.
"""
import logging
from datetime import date

import httpx

logger = logging.getLogger("exchange_rate")

# currency -> (date, per_unit_rate, source)
_cache: dict[str, tuple] = {}

_DUNAMU = "https://quotation-api-cdn.dunamu.com/v1/forex/recent"
_ERAPI = "https://open.er-api.com/v6/latest/{cur}"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.dunamu.com/"}


async def _fetch_dunamu(currency: str) -> float:
    """Dunamu(하나은행 기준). basePrice/currencyUnit = 1단위당 원화."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(_DUNAMU, params={"codes": f"FRX.KRW{currency}"}, headers=_HEADERS)
        r.raise_for_status()
        data = r.json()
        if data:
            base = data[0].get("basePrice") or 0
            unit = data[0].get("currencyUnit") or 1
            if base:
                return round(base / unit, 4)
    return 0.0


async def _fetch_erapi(currency: str) -> float:
    """open.er-api.com 폴백. rates.KRW = 1단위당 원화."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(_ERAPI.format(cur=currency))
        r.raise_for_status()
        data = r.json()
        krw = (data.get("rates") or {}).get("KRW")
        return round(float(krw), 4) if krw else 0.0


async def get_exchange_rate(currency: str = "JPY") -> float:
    """1 통화단위당 원화 환율. 같은 날 캐시. 실패 시 직전 캐시, 없으면 0."""
    currency = currency.upper()
    today = date.today()
    cached = _cache.get(currency)
    if cached and cached[0] == today and cached[1]:
        return cached[1]

    rate, source = 0.0, ""
    for name, fn in (("dunamu", _fetch_dunamu), ("er-api", _fetch_erapi)):
        try:
            rate = await fn(currency)
            if rate:
                source = name
                break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[exchange_rate] {name} {currency} 실패: {e}")

    if rate:
        _cache[currency] = (today, rate, source)
        logger.info(f"[exchange_rate] {currency} = {rate}원 ({source})")
        return rate

    if cached and cached[1]:
        logger.warning(f"[exchange_rate] 라이브 실패 → 직전 캐시({cached[0]}) {cached[1]}원 사용")
        return cached[1]
    return 0.0


async def get_exchange_rate_meta(currency: str = "JPY") -> dict:
    """환율 + 출처/날짜 메타 (화면 표시용)."""
    rate = await get_exchange_rate(currency)
    cached = _cache.get(currency.upper())
    return {
        "currency": currency.upper(),
        "rate": rate,
        "source": cached[2] if cached else "",
        "as_of": cached[0].isoformat() if cached else "",
    }
