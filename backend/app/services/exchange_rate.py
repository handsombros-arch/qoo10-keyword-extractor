import httpx


async def get_exchange_rate(currency: str = "JPY") -> float:
    """환율 조회 (KEB 하나은행 기준)"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://quotation-api-cdn.dunamu.com/v1/forex/recent",
                params={"codes": f"FRX.KRW{currency.upper()}"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            data = resp.json()
            if data:
                return data[0].get("basePrice", 0)
    except Exception:
        pass
    return 0
