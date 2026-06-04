"""Papago 웹사이트(papago.naver.com) 자동화 번역 — 원본 키워드 추출기와 동일 방식.

원본 VBA(번역_일본어to한국어)는 NCP 유료 API가 아니라 **papago.naver.com 웹페이지를
Selenium으로 구동**해 무료로 고품질 번역(브랜드 음역 안정)을 얻는다. 엘비텐도 동일하게
Playwright(실 Chrome)로 구동.

핵심:
- URL: https://papago.naver.com/?sk=ja&tk=ko&hn=0&st=<URL인코딩 텍스트>
- 여러 줄을 한 번에 번역(줄바꿈 구분) → 결과도 줄바꿈으로 분리(배치 효율).
- 결과 셀렉터: #txtTarget (원본 driver.FindElementsById("txtTarget")).
"""
from urllib.parse import quote

_RESULT_SEL = "#txtTarget"


async def papago_translate_batch(
    page, texts: list[str], source: str = "ja", target: str = "ko", wait_ms: int = 5000
) -> list[str] | None:
    """papago.naver.com 으로 texts 배치 번역. 입력 줄 수와 결과 줄 수가 맞으면 매핑 반환.
    실패/불일치 시 None (호출측이 구글 폴백)."""
    texts = [t for t in texts]
    if not texts:
        return []

    joined = "\n".join(texts)
    url = f"https://papago.naver.com/?sk={source}&tk={target}&hn=0&st={quote(joined, safe='')}"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # 결과가 채워질 때까지 폴링 (SPA 번역 지연). 입력 줄 수 이상 차면 완료.
        result = ""
        steps = max(10, wait_ms // 300)
        for _ in range(steps):
            await page.wait_for_timeout(300)
            el = await page.query_selector(_RESULT_SEL)
            if not el:
                continue
            txt = (await el.inner_text()).strip()
            if not txt:
                continue
            result = txt
            if len(txt.split("\n")) >= len(texts):
                break
        if not result:
            return None

        lines = result.split("\n")
        # 줄 수 불일치 = 매핑 신뢰 불가 → None (구글 폴백)
        if len(lines) != len(texts):
            return None
        return [ln.strip() for ln in lines]
    except Exception:
        return None
