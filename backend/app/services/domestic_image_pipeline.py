"""한국 시장(네이버/쿠팡) 상품 이미지 다운로드 + 비전 평가 + 폴더링.

흐름:
    1) DomesticProduct.cover_image_url 다운로드 → 임시 파일
    2) PIL 리사이즈 (max 1024) — _image_utils.resize_for_upload
    3) 비전 평가 — score_product_image_async (4 항목 점수)
    4) image/{date}/{kr_product_name}/cover.jpg 로 정식 저장
    5) DB UPDATE: image_local_path, image_score_overall, image_score_json

폴더 안전 처리:
    - Windows 파일명 금지 문자 (\\/:*?\"<>|) 제거
    - 길이 100자 제한, 공백 → _
"""
from __future__ import annotations

import json as _json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.services.llm.vision import score_product_image_async

logger = logging.getLogger(__name__)

# 프로젝트 루트의 image/ — backend/app/services/ → 3단계 위
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
IMAGE_ROOT = _PROJECT_ROOT / "image"

# Windows 금지 문자 + 일부 도구가 path 처리 시 특별 취급하는 보수적 추가셋
# (대괄호/중괄호/괄호/느낌표/물음표/세미콜론/쉼표/달러)
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t\[\]\{\}\(\)!;,\$]')
_WHITESPACE = re.compile(r"\s+")


def _safe_folder_name(name: str, max_len: int = 100) -> str:
    """Windows 안전 + 보수적 특수문자 제거 + 100자 제한 + 공백→_ 폴더명.

    [, ], (, ) 등은 OS 자체는 허용하지만 일부 라이브러리/스크립트 처리에서
    파싱 충돌을 일으킬 수 있어 미리 제거. 기존 폴더와 호환성은 깨지지만
    DB의 image_local_path 가 새 규칙으로 다시 채워지면서 자연스럽게 정합화.
    """
    s = (name or "").strip()
    s = _INVALID_CHARS.sub("", s)
    s = _WHITESPACE.sub("_", s)
    s = s.strip("._-")
    if not s:
        s = "untitled"
    return s[:max_len]


def _date_dir(date_str: str) -> Path:
    d = IMAGE_ROOT / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


async def download_to_temp(url: str, timeout: float = 15.0) -> str | None:
    """이미지를 임시 파일로 다운로드. 실패 시 None.

    User-Agent 설정: 네이버 CDN 등이 일부 클라이언트 차단 회피.
    """
    if not url:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content
    except Exception as e:
        logger.warning(f"[image_pipeline] 다운로드 실패 {url[:80]}: {e}")
        return None

    if not data or len(data) < 200:
        return None

    # 확장자는 jpg 통일 (resize_for_upload 가 jpeg 로 변환)
    tmp = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        return tmp.name
    except Exception:
        try:
            tmp.close()
        except Exception:
            pass
        return None


async def download_score_save(
    *,
    product_id: int,
    cover_url: str,
    product_name_kr: str,
    category: str,
    date_str: str,
    source: str = "src",
) -> dict[str, Any]:
    """한 상품 이미지 처리: 다운로드 → 비전 평가 → 저장.

    파일명: {source}_{product_id}.jpg (overwrite 방지 — 같은 product_name 여러 행 모두 보존).

    Returns:
        {
          "ok": bool,
          "local_path": str | None (project root 기준 상대경로),
          "score": dict | None (vision score),
          "overall": float,
          "note": str,
        }
    """
    out: dict[str, Any] = {
        "ok": False, "local_path": None, "score": None, "overall": 0.0, "note": "",
    }

    if not cover_url:
        out["note"] = "no_cover_url"
        return out

    tmp_path = await download_to_temp(cover_url)
    if not tmp_path:
        out["note"] = "download_failed"
        return out

    try:
        # 비전 평가 (vision.py 가 내부에서 PIL 리사이즈 + 임시 파일 처리)
        score = await score_product_image_async(tmp_path, category=category or "기타")
        out["score"] = score
        out["overall"] = float(score.get("overall_score", 0.0) or 0.0)

        if not score.get("ok"):
            out["note"] = score.get("note") or "vision_failed"
            # vision 이 실패해도 이미지 저장은 시도 (사장님이 직접 볼 수 있게)

        # 폴더 정식 저장 (모두 저장 정책 — 점수 임계값 X)
        # 파일명에 source + id → 같은 product_name 의 여러 행 모두 보존
        folder_name = _safe_folder_name(product_name_kr or f"product_{product_id}")
        dest_dir = _date_dir(date_str) / folder_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe_source = (source or "src").lower().replace(" ", "_")[:10]
        dest_path = dest_dir / f"{safe_source}_{product_id}.jpg"

        # tmp 가 이미 jpg 라면 복사, 아니면 PIL 로 변환 저장
        try:
            from PIL import Image
            with Image.open(tmp_path) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(dest_path, "JPEG", quality=88, optimize=True)
        except Exception as e:
            # PIL 실패 시 raw copy 폴백
            logger.warning(f"[image_pipeline] PIL 저장 실패 → raw copy: {e}")
            shutil.copyfile(tmp_path, dest_path)

        # 프로젝트 루트 기준 상대경로
        try:
            rel = dest_path.relative_to(_PROJECT_ROOT).as_posix()
        except ValueError:
            rel = str(dest_path)
        out["local_path"] = rel
        out["ok"] = True
        if not out["note"]:
            out["note"] = "saved"
        return out
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


__all__ = [
    "IMAGE_ROOT",
    "download_to_temp",
    "download_score_save",
    "_safe_folder_name",
]
