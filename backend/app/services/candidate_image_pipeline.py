"""auto-build 후보별 이미지 폴더 생성 (DDD-1).

기존 domestic_image_pipeline 은 m08 결과 30개 모두 cover 다운 → 폴더 30개 (낭비).
신규: auto-build 후 candidates (final_score 통과) 만 keyword 단위 폴더로 묶음.

폴더 구조:
    image/{date}/{keyword_jp_safe}/
        meta.json                       — keyword/translation/cheapest/alts 추적
        cover_naver_{id}.jpg            — cheapest cover (시트 row.cover_image_url)
        alt_naver_{id}_{price}원.jpg    — 가격 N위 (참고, 비교)
        extras/                          — scrape 상세 이미지 (별도)

사용:
    await build_candidate_folders(target_date, candidates_payload)
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.services.domestic_image_pipeline import (
    IMAGE_ROOT, _safe_folder_name, download_to_temp,
)

logger = logging.getLogger(__name__)


def _keyword_folder(date_str: str, keyword_jp: str) -> Path:
    """keyword_jp 단위 폴더. m08 결과 무관 — 한 keyword = 한 폴더."""
    safe = _safe_folder_name(keyword_jp)
    folder = IMAGE_ROOT / date_str / safe
    folder.mkdir(parents=True, exist_ok=True)
    return folder


async def _download_to(url: str, dest: Path) -> bool:
    """URL → dest 파일 다운로드. PIL 변환 없이 raw."""
    if not url or dest.exists():
        return dest.exists()
    tmp_path = await download_to_temp(url)
    if not tmp_path:
        return False
    try:
        # PIL 로 RGB JPEG 변환 (파일명은 dest 그대로)
        try:
            from PIL import Image
            with Image.open(tmp_path) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(dest, "JPEG", quality=88, optimize=True)
        except Exception:
            shutil.copyfile(tmp_path, dest)
        return True
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


async def build_candidate_folders(
    date_str: str,
    candidates: list[dict],
    *,
    alt_count: int = 3,
) -> dict:
    """auto-build candidates → keyword 폴더 + meta.json.

    candidates: auto-build 가 만든 user_data.last_auto_collected snapshot.
    alt_count: cheapest 외 가격 순 N개 더 다운 (참고용).

    Returns: {processed: int, skipped: int, folders: [paths...]}
    """
    from app.db.connection import async_session
    from app.db.models import DomesticProduct
    from sqlalchemy import select

    processed = 0
    skipped = 0
    folder_paths: list[str] = []

    for c in candidates:
        kw_jp = c.get("keyword_jp")
        if not kw_jp:
            skipped += 1
            continue
        ch = c.get("cheapest_domestic") or {}
        if not ch.get("id") or not ch.get("cover_image_url"):
            skipped += 1
            continue

        folder = _keyword_folder(date_str, kw_jp)

        # 1) cheapest cover 다운
        ch_id = ch["id"]
        ch_price = ch.get("price_krw") or 0
        cover_file = folder / f"cover_{(ch.get('source') or 'src')}_{ch_id}.jpg"
        await _download_to(ch.get("cover_image_url") or "", cover_file)

        # 2) alt covers — 같은 keyword 의 다른 한국 SKU 가격 순 alt_count
        alts: list[dict] = []
        try:
            async with async_session() as s:
                r = await s.execute(
                    select(DomesticProduct.id, DomesticProduct.product_name,
                           DomesticProduct.price_krw, DomesticProduct.product_url,
                           DomesticProduct.cover_image_url, DomesticProduct.source,
                           DomesticProduct.image_score_overall)
                    .where(DomesticProduct.search_keyword == c.get("keyword_kr"))
                    .where(DomesticProduct.id != ch_id)
                    .where(DomesticProduct.cover_image_url.is_not(None))
                    .where(DomesticProduct.price_krw > 0)
                    .order_by(DomesticProduct.price_krw.asc())
                    .limit(alt_count)
                )
                for aid, aname, aprice, aurl, acov, asrc, ascore in r.all():
                    alt_file = folder / f"alt_{(asrc or 'src')}_{aid}_{aprice}원.jpg"
                    await _download_to(acov or "", alt_file)
                    alts.append({
                        "domestic_id": aid,
                        "product_name": aname,
                        "price_krw": aprice,
                        "url": aurl,
                        "cover_url": acov,
                        "image_score_overall": ascore,
                        "file": alt_file.name,
                    })
        except Exception as e:
            logger.warning(f"[candidate_image] alt 조회 실패 {kw_jp}: {e}")

        # 3) meta.json — keyword/translation/cheapest/alts 추적
        meta = {
            "keyword_jp": kw_jp,
            "keyword_kr": c.get("keyword_kr"),
            "qoo10_count": c.get("qoo10_count"),
            "qoo10_avg_jpy": c.get("qoo10_avg_jpy"),
            "qoo10_min_jpy": c.get("qoo10_min_jpy"),
            "qoo10_max_jpy": c.get("qoo10_max_jpy"),
            "search_volume": c.get("search_volume"),
            "kr_ratio": c.get("kr_ratio"),
            "competition_intensity": c.get("competition_intensity"),
            "cheapest": {
                "domestic_id": ch_id,
                "product_name": ch.get("product_name"),
                "price_krw": ch_price,
                "url": ch.get("product_url"),
                "cover_url": ch.get("cover_image_url"),
                "source": ch.get("source"),
                "match_source": ch.get("match_source"),
                "file": cover_file.name,
            },
            "alts": alts,
            "margin": c.get("margin"),
            "final_score": c.get("final_score"),
            "generated_at": datetime.utcnow().isoformat(),
        }
        try:
            (folder / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[candidate_image] meta.json 쓰기 실패: {e}")

        processed += 1
        folder_paths.append(str(folder))

    logger.info(f"[candidate_image] 완료 — {processed} 폴더, skipped {skipped}")
    return {
        "processed": processed,
        "skipped": skipped,
        "folders": folder_paths,
    }


__all__ = ["build_candidate_folders"]
