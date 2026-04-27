"""비전 호출용 이미지 전처리.

업로드 전에 max 1024×1024 (env VISION_MAX_IMAGE_PX) 로 비율 유지 리사이즈.
JPEG 품질 85, RGB 변환 (PNG 알파 → 흰 배경).
원본 파일은 손대지 않고 임시 파일을 새로 만들어 경로 반환.

호출자는 사용 후 cleanup_temp(path) 로 임시 파일 삭제.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_MAX_PX = 1024


def _max_px() -> int:
    try:
        return int(os.getenv("VISION_MAX_IMAGE_PX", str(_DEFAULT_MAX_PX)))
    except ValueError:
        return _DEFAULT_MAX_PX


def resize_for_upload(image_path: str) -> str:
    """원본을 max_px 로 리사이즈하고 임시 JPEG 경로 반환.

    원본이 이미 작으면 그대로 복사 (변환만 — 형식 통일).
    실패 시 원본 경로 그대로 반환 (호출 흐름 막지 않음).
    """
    src = Path(image_path)
    if not src.exists():
        logger.warning(f"[image] 파일 없음: {image_path}")
        return image_path

    try:
        from PIL import Image
    except ImportError:
        logger.warning("[image] Pillow 미설치 — 원본 그대로 업로드")
        return image_path

    try:
        with Image.open(src) as img:
            # PNG 알파 → 흰 배경 RGB
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            max_px = _max_px()
            w, h = img.size
            if max(w, h) > max_px:
                if w >= h:
                    new_w, new_h = max_px, int(h * max_px / w)
                else:
                    new_w, new_h = int(w * max_px / h), max_px
                img = img.resize((new_w, new_h), Image.LANCZOS)

            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.close()
            img.save(tmp.name, "JPEG", quality=85, optimize=True)
            return tmp.name
    except Exception as e:
        logger.warning(f"[image] 리사이즈 실패 ({e}) — 원본 그대로 업로드")
        return image_path


def cleanup_temp(path: str, original_path: str) -> None:
    """리사이즈된 임시 파일이면 삭제. 원본과 같은 경로면 무시."""
    if not path or path == original_path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


__all__ = ["resize_for_upload", "cleanup_temp"]
