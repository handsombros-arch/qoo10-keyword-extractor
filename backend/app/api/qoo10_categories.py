"""큐텐 등록 카테고리 (V, 5/3) — Qoo10_CategoryInfo.csv 로드 + 검색.

CSV: 프로젝트 루트의 Qoo10_CategoryInfo.csv (3004개 카테고리, 3-level: 대/중/소).
사장님이 큐텐 등록 시 정확한 카테고리 코드 (소카테고리 코드) 가 필요.

캐싱: 첫 호출 시 메모리 로드, 이후 cached.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

_CSV_PATH = Path(__file__).resolve().parents[3] / "Qoo10_CategoryInfo.csv"
_CACHE: list[dict] | None = None


def _load() -> list[dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not _CSV_PATH.exists():
        logger.error(f"[qoo10_categories] CSV 없음: {_CSV_PATH}")
        _CACHE = []
        return _CACHE
    rows: list[dict] = []
    try:
        with open(_CSV_PATH, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                l_name = r.get("대카테고리 명", "").strip()
                m_name = r.get("중카테고리 명", "").strip()
                s_name = r.get("소카테고리 명", "").strip()
                rows.append({
                    "l_code": r.get("대카테고리 코드", "").strip(),
                    "l_name": l_name,
                    "m_code": r.get("중카테고리 코드", "").strip(),
                    "m_name": m_name,
                    "s_code": r.get("소카테고리 코드", "").strip(),
                    "s_name": s_name,
                    "path": f"{l_name} > {m_name} > {s_name}",
                })
        logger.info(f"[qoo10_categories] {len(rows)}개 로드")
    except Exception as e:
        logger.error(f"[qoo10_categories] 로드 실패: {e}")
        rows = []
    _CACHE = rows
    return _CACHE


@router.get("/api/qoo10-categories")
async def list_categories(q: Optional[str] = None) -> dict:
    """전체 카테고리 또는 검색.

    q 파라미터 시 l/m/s 이름 모두에서 substring 매칭 (대소문자 무시).
    """
    items = _load()
    if q:
        q_lower = q.strip().lower()
        if q_lower:
            items = [
                it for it in items
                if q_lower in it["l_name"].lower()
                or q_lower in it["m_name"].lower()
                or q_lower in it["s_name"].lower()
            ]
    return {"items": items, "total": len(items)}


@router.get("/api/qoo10-categories/{s_code}")
async def get_by_code(s_code: str) -> dict:
    for r in _load():
        if r["s_code"] == s_code:
            return r
    return {"error": "not found"}
