"""EasyOCR 기반 이미지/스크린샷 텍스트 추출.

Phase 2.5 OCR 폴백 (kc-cert-checker 패턴):
    HTML 가격 selector 실패 시 페이지 스크린샷 또는 상세 이미지 → OCR → 가격/배송비 정규식.

env:
    OCR_GPU=1                (기본, GPU 사용)
    OCR_LANGS=ko,en          (기본)

사용:
    text = await ocr_image_async("path.jpg")
    price = extract_price_from_text(text)
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_reader():
    """EasyOCR Reader 싱글톤 (모델 로드 ~3초, 그 후 빠름)."""
    try:
        import easyocr
    except ImportError as e:
        raise RuntimeError("easyocr 미설치") from e
    use_gpu = os.getenv("OCR_GPU", "1") == "1"
    langs_str = os.getenv("OCR_LANGS", "ko,en")
    langs = [s.strip() for s in langs_str.split(",") if s.strip()]
    logger.info(f"[ocr] EasyOCR Reader 초기화 (langs={langs}, gpu={use_gpu})")
    return easyocr.Reader(langs, gpu=use_gpu, verbose=False)


def _preprocess_for_ocr(image_bytes: bytes) -> bytes:
    """이미지 전처리 — 작은 글씨 인식 향상 (kc 방식).

    2배 확대 + CLAHE 고대비 + 샤프닝 + 적응적 이진화.
    원본 그대로 OCR 실패 시 호출.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return image_bytes

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes

    h, w = img.shape[:2]
    img = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharp = cv2.filter2D(gray, -1, kernel)

    bin_img = cv2.adaptiveThreshold(
        sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )

    ok, encoded = cv2.imencode(".png", bin_img)
    return encoded.tobytes() if ok else image_bytes


def _ocr_bytes_sync(image_bytes: bytes, preprocess: bool = False) -> str:
    """동기 OCR — asyncio.to_thread 로 호출."""
    if preprocess:
        image_bytes = _preprocess_for_ocr(image_bytes)
    try:
        reader = _get_reader()
        result = reader.readtext(image_bytes, detail=0, paragraph=True)
        if isinstance(result, list):
            return "\n".join(str(s) for s in result if s)
        return str(result or "")
    except Exception as e:
        logger.warning(f"[ocr] readtext 실패 (preprocess={preprocess}): {e}")
        return ""


async def ocr_image_async(image_path_or_bytes) -> str:
    """이미지 → 텍스트. 원본 OCR 실패 시 전처리 후 재시도.

    image_path_or_bytes: str 경로 또는 bytes
    """
    if isinstance(image_path_or_bytes, (str, Path)):
        try:
            data = Path(image_path_or_bytes).read_bytes()
        except Exception as e:
            logger.warning(f"[ocr] 파일 읽기 실패 {image_path_or_bytes}: {e}")
            return ""
    elif isinstance(image_path_or_bytes, (bytes, bytearray)):
        data = bytes(image_path_or_bytes)
    else:
        return ""

    if not data or len(data) < 200:
        return ""

    # 1차 — 원본
    text = await asyncio.to_thread(_ocr_bytes_sync, data, False)
    if _is_meaningful(text):
        return text

    # 2차 — 전처리
    text2 = await asyncio.to_thread(_ocr_bytes_sync, data, True)
    return text2


def _is_meaningful(text: str) -> bool:
    """OCR 결과가 의미 있는지 — 한글/영문/숫자 5글자 이상."""
    if not text:
        return False
    cleaned = re.sub(r"\s+", "", text)
    return len(cleaned) >= 5


_PRICE_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})+)\s*원?")


def extract_prices_from_text(text: str) -> list[int]:
    """OCR 텍스트에서 가격 후보 추출 (1000~10M KRW 만)."""
    if not text:
        return []
    nums = []
    for m in _PRICE_PATTERN.finditer(text):
        try:
            n = int(m.group(1).replace(",", ""))
            if 1000 <= n <= 10_000_000:
                nums.append(n)
        except ValueError:
            continue
    return nums


def extract_price_main(text: str) -> Optional[int]:
    """가장 빈번한 가격 (메인 가격일 가능성)."""
    nums = extract_prices_from_text(text)
    if not nums:
        return None
    return Counter(nums).most_common(1)[0][0]


__all__ = [
    "ocr_image_async",
    "extract_prices_from_text",
    "extract_price_main",
]
