"""Qoo10 JP 상세페이지 카피 자동 생성 (AAAA-1).

qoo10-jp-detail-master.md 가이드 기반:
  - 입력: Naver URL OR 직접 (product_name + detail_image_urls)
  - 처리: OCR (EasyOCR) + product info → LLM (qwen3:14b)
  - 출력: JSON (인트로 6블록 + POINT 1-3 + 추천 4불릿 + 면책)

env: QOO10_CONTENT_MODEL (qwen3:14b 권장)
prompt: app/services/llm/prompts/qoo10_jp_detail.txt
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
from pathlib import Path

import httpx

from app.services.llm.router import get_client_for, load_prompt
from app.services.ocr import ocr_image_async

logger = logging.getLogger(__name__)


_STEALTH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": "https://search.shopping.naver.com/",
}


async def _download_image(url: str, timeout: float = 15.0) -> str | None:
    """URL → 임시 파일 다운로드. 실패 시 None."""
    if not url or not url.startswith("http"):
        return None
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=_STEALTH_HEADERS,
        ) as c:
            r = await c.get(url)
            r.raise_for_status()
            data = r.content
        if len(data) < 200:
            return None
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(data)
        tmp.close()
        return tmp.name
    except Exception as e:
        logger.debug(f"[jp_detail] image download fail {url[:50]}: {e}")
        return None


async def ocr_detail_images(image_urls: list[str], max_images: int = 10) -> list[str]:
    """상세 이미지 N개 OCR → text list (빈 결과는 제외)."""
    if not image_urls:
        return []
    texts: list[str] = []
    for url in image_urls[:max_images]:
        path = await _download_image(url)
        if not path:
            continue
        try:
            text = await ocr_image_async(path)
            if text and text.strip():
                texts.append(text.strip())
        except Exception as e:
            logger.debug(f"[jp_detail] ocr fail {url[:50]}: {e}")
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
        # 짧은 sleep — vision LLM 과부하 회피
        await asyncio.sleep(0.05)
    return texts


def _strip_codefence(s: str) -> str:
    s = re.sub(r"^```(?:json)?\s*", "", s.strip())
    s = re.sub(r"\s*```\s*$", "", s)
    return s


def _category_guidance(category: str) -> str:
    """카테고리별 카피 가이던스 — 적합 키워드 + 금지 단어 + 패턴 예시.

    프롬프트의 `{category_guidance}` 자리에 주입. 카테고리 매칭은 substring (포함) 기준.
    매칭 안 되면 `기타` 가이던스. (R-7 6분류 기준 + 패션/식품/가전/생활 확장)
    """
    c = (category or "").lower()
    # 매칭 우선순위 — 더 구체적인 카테고리 먼저
    if any(k in c for k in ["뷰티", "화장품", "코스메", "스킨", "코스노", "cosme"]):
        return _GUIDANCE_BEAUTY
    if any(k in c for k in ["식품", "건강식품", "건강기능", "다이어트", "비타민", "프로틴", "food"]):
        return _GUIDANCE_FOOD
    if any(k in c for k in ["패션", "잡화", "가방", "백팩", "의류", "신발", "악세", "fashion"]):
        return _GUIDANCE_FASHION
    if any(k in c for k in ["가전", "디지털", "전자", "컴퓨터", "폰", "기기"]):
        return _GUIDANCE_ELECTRONICS
    if any(k in c for k in ["생활", "건강", "주방", "리빙", "유아", "반려"]):
        return _GUIDANCE_LIVING
    return _GUIDANCE_GENERIC


_GUIDANCE_BEAUTY = """【카테고리: 뷰티/화장품 — 적합 표현】
- pain points 예: 毛穴/くすみ/カサつき/メイク崩れ/敏感肌
- 어필 키워드: 角質ケア/うるおい/ハリ/つや/くすみケア/さっぱり
- 약사법 회피 (효능 단정 X): 効果がある→～な印象に* | シワがなくなる→ハリ印象* | 美白→メラニンの生成を抑える*
- 의태어: しっとり/もっちり/ぴたっと/ぷるん/つるん"""

_GUIDANCE_FASHION = """【카테고리: 패션/잡화 — 적합 표현】
- pain points 예: デザインが平凡/サイズが合わない/重くて疲れる/収納が足りない/季節感がない
- 어필 키워드: 軽量/コンパクト/シルエット/カラー/素材感/フィット感/コーデ/オン・オフ
- 약사법 적용 X (footnotes 빈 배열)
- 화장품 단어 (毛穴/肌/シワ/角質/メラニン) 절대 X
- 의태어: ぴたっと/きゅっと/さらさら/つるん/ふんわり"""

_GUIDANCE_FOOD = """【카테고리: 식품 — 적합 표현】
- pain points 예: 味が濃すぎる/カロリーが気になる/手軽に食べたい/賞味期限が短い
- 어필 키워드: 旨味/コク/食感/香り/素材/産地/手軽/低カロリー/ヘルシー
- 약사법/건강식품 표현 단정 X (효능 단정 시 * 면책)
- 의태어: ふっくら/もっちり/さくさく/とろん/しゃきしゃき"""

_GUIDANCE_ELECTRONICS = """【카테고리: 가전/디지털 — 적합 표현】
- pain points 예: 操作が複雑/サイズが大きい/電池がすぐ切れる/騒音が気になる
- 어필 키워드: 高性能/操作簡単/省エネ/コンパクト/軽量/長持ちバッテリー/静音
- 약사법 적용 X
- 화장품/식품 단어 절대 X
- 의태어 신중히 사용 (제품 특성 맞을 때만)"""

_GUIDANCE_LIVING = """【카테고리: 생활/건강/주방 — 적합 표현】
- pain points 예: 収納が足りない/掃除が大変/サイズが合わない/壊れやすい
- 어필 키워드: 便利/丈夫/軽量/コンパクト/お手入れ簡単/省スペース/清潔
- 약사법 일반적으로 적용 X (건강용품은 일부 적용)
- 화장품/식품 단어 절대 X
- 의태어: しっかり/すっきり/さらさら/ふんわり"""

_GUIDANCE_GENERIC = """【카테고리: 일반/기타 — 적합 표현】
- 상품명/OCR 텍스트로부터 카테고리 추정 후 그에 맞춰 작성
- 화장품 전용 단어 (毛穴/肌/シワ/角質/メラニン) 사용 금지
- 식품 전용 단어 (旨味/コク/賞味期限) 사용 금지
- 가전 전용 단어 (高性能/省エネ) 사용 금지
- 상품명에서 명백히 도출되는 어필 포인트만 사용"""


async def generate_jp_detail(
    korean_name: str,
    *,
    category: str = "",
    key_features: list[str] | None = None,
    ocr_texts: list[str] | None = None,
) -> dict:
    """LLM 호출 → 인트로/POINT/추천 YAML 구조.

    실패 시 {error, ...}.
    """
    if not korean_name:
        return {"error": "korean_name 필수"}

    # OCR 텍스트 결합 (각 이미지 ===== separator)
    ocr_block = ""
    if ocr_texts:
        ocr_block = "\n\n=====\n\n".join(t[:2000] for t in ocr_texts[:8])
    if not ocr_block:
        ocr_block = "(상세 이미지 OCR 결과 없음 — 한국 상품명으로만 추론)"

    features_block = ""
    if key_features:
        features_block = ", ".join(key_features[:10])
    else:
        features_block = "(없음)"

    try:
        client = get_client_for("qoo10_jp_detail")
    except Exception as e:
        return {"error": f"LLM 클라이언트 실패: {e}"}

    prompt = (
        load_prompt("qoo10_jp_detail")
        .replace("{korean_name}", korean_name)
        .replace("{category}", category or "(미상)")
        .replace("{key_features}", features_block)
        .replace("{ocr_text}", ocr_block[:8000])
        .replace("{category_guidance}", _category_guidance(category or ""))
    )

    try:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            json_mode=True,
            max_tokens=8192,
        )
    except Exception as e:
        return {"error": f"LLM 호출 실패: {e}"}

    text = (result.text or "").strip()
    if not text:
        return {"error": "빈 응답"}

    s = _strip_codefence(text)
    parsed = None

    def _try_parse(s2: str) -> dict | None:
        try:
            r = json.loads(s2)
            return r if isinstance(r, dict) else None
        except json.JSONDecodeError:
            return None

    # 1. 엄격 파싱
    parsed = _try_parse(s)

    # 2. lenient — 흔한 LLM 오류 fix
    if not parsed:
        s_fixed = s
        s_fixed = s_fixed.replace('"', '"').replace('"', '"')
        s_fixed = s_fixed.replace("'", "'").replace("'", "'")
        # trailing comma
        s_fixed = re.sub(r",(\s*[}\]])", r"\1", s_fixed)
        # 첫 { 부터 마지막 } 까지만
        m_start = s_fixed.find("{")
        m_end = s_fixed.rfind("}")
        if m_start >= 0 and m_end > m_start:
            s_fixed = s_fixed[m_start:m_end + 1]
        parsed = _try_parse(s_fixed)

    # 3. ULTRA lenient — incremental: 마지막 } 부터 줄여가며 valid JSON 찾기
    if not parsed:
        s_fixed = s
        m_start = s_fixed.find("{")
        if m_start >= 0:
            for end_pos in range(len(s_fixed), m_start, -1):
                s_try = s_fixed[m_start:end_pos]
                if not s_try.endswith("}"):
                    continue
                # trailing comma 제거
                s_try = re.sub(r",(\s*[}\]])", r"\1", s_try)
                p = _try_parse(s_try)
                if p:
                    parsed = p
                    break

    # 4. 최종 폴백 — 최소한의 partial 결과 (intro 만이라도)
    if not parsed:
        # raw 를 임시 파일로 저장 (사장님 디버그용)
        from pathlib import Path
        from datetime import datetime
        try:
            debug_dir = Path("logs") / "llm_failures"
            debug_dir.mkdir(parents=True, exist_ok=True)
            fname = debug_dir / f"jp_detail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            fname.write_text(text, encoding="utf-8")
            saved_path = str(fname)
        except Exception:
            saved_path = ""
        return {
            "error": f"JSON 파싱 실패 — LLM 응답이 valid JSON 아님 (raw 길이 {len(text)})",
            "raw_preview": text[:600],
            "raw_tail": text[-300:] if len(text) > 600 else "",
            "raw_length": len(text),
            "saved_to": saved_path,
        }

    return parsed


async def generate_from_url(
    naver_url: str,
    *,
    fallback_name: str = "",
) -> dict:
    """URL → 모든 단계 자동 (fetch → OCR → LLM).

    fetch 실패 시 fallback_name 으로 LLM 만 시도 (OCR X).
    """
    # BBBB-1: Playwright 기반 v2 (kc-cert-checker 패턴) 사용
    from app.services.naver_fetch_v2 import fetch_naver_url_v2

    info = await fetch_naver_url_v2(naver_url, headless=True)
    if "error" in info:
        if not fallback_name:
            return {
                "error": f"fetch 실패 ({info['error']}). fallback_name 제공 필요",
                "hint": "사장님이 직접 product_name + detail_image_urls 제공하면 진행 가능",
            }
        # fallback: name 만 있고 OCR 없음
        result = await generate_jp_detail(
            korean_name=fallback_name,
            category="",
            key_features=[],
            ocr_texts=[],
        )
        result["_source"] = "fallback (no OCR)"
        return result

    detail_urls = info.get("extra_image_urls") or []
    ocr_texts = await ocr_detail_images(detail_urls, max_images=8)

    # description 도 OCR text 처럼 LLM 에 전달 (참고)
    if info.get("description"):
        ocr_texts.insert(0, f"[Naver description] {info['description']}")

    result = await generate_jp_detail(
        korean_name=info.get("product_name") or fallback_name,
        category=info.get("category_path") or "",
        key_features=[],
        ocr_texts=ocr_texts,
    )
    result["_source"] = {
        "url": naver_url,
        "name": info.get("product_name"),
        "category": info.get("category_path"),
        "ocr_count": len(ocr_texts),
        "detail_image_count": len(detail_urls),
    }
    return result


__all__ = ["generate_jp_detail", "generate_from_url", "ocr_detail_images"]
