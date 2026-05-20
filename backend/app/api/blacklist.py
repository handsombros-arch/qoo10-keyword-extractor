"""블랙리스트 — 시장 분석/수집은 계속 (RD 데이터 보존), 시트 추가만 사전 차단.

UserData "blacklist" 키에 JSON 배열 저장:
    [
      {
        "id": "uuid",
        "keyword_jp": "BTS Arirang",     # optional
        "product_name": "...",            # optional (Korean)
        "reason": "K-pop 팬굿즈, 소싱 계획 X",  # optional
        "added_at": "2026-05-03T...",
        "source": "manual" | "auto"
      },
      ...
    ]

매칭 우선순위 (사장님 예시 "BTS Arirang" 같은 K-pop 팬굿즈 차단 의도):
    1) keyword_jp 정확 매칭 (대소문자/공백 정규화)
    2) product_name 정확 매칭

자동화 통합:
    - send-to-sheet 가 시트 추가 전 _is_blacklisted() 호출 → 매칭 시 skip
    - 향후 keyword RD STEP 4 자동 필터에도 적용 가능
"""
from __future__ import annotations

import json as jsonlib
import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.connection import async_session
from app.db.models import UserData

logger = logging.getLogger(__name__)
router = APIRouter()

_KEY = "blacklist"


def _normalize(s: str | None) -> str:
    """매칭용 정규화 — 공백 압축 + 양끝 제거 + 소문자."""
    if not s:
        return ""
    return " ".join(str(s).split()).strip().lower()


async def _load_blacklist() -> list[dict]:
    """UserData 에서 blacklist 로드. 없으면 빈 배열."""
    async with async_session() as s:
        r = await s.execute(select(UserData).where(UserData.key == _KEY))
        row = r.scalar_one_or_none()
    if not row or not row.data:
        return []
    try:
        data = jsonlib.loads(row.data)
        return data if isinstance(data, list) else []
    except Exception:
        logger.warning(f"[blacklist] JSON 파싱 실패 — 빈 배열로 복구")
        return []


async def _save_blacklist(items: list[dict]) -> None:
    payload = jsonlib.dumps(items, ensure_ascii=False)
    now = datetime.utcnow()
    async with async_session() as s:
        r = await s.execute(select(UserData).where(UserData.key == _KEY))
        row = r.scalar_one_or_none()
        if row:
            row.data = payload
            row.updated_at = now
        else:
            s.add(UserData(key=_KEY, data=payload, updated_at=now))
        await s.commit()


async def is_blacklisted(*, keyword_jp: str = "", product_name: str = "") -> bool:
    """자동화/송신 전 사전 차단 체크용. 매칭 시 True."""
    items = await _load_blacklist()
    if not items:
        return False
    nkw = _normalize(keyword_jp)
    npn = _normalize(product_name)
    if not nkw and not npn:
        return False
    for it in items:
        ikw = _normalize(it.get("keyword_jp"))
        ipn = _normalize(it.get("product_name"))
        if nkw and ikw and nkw == ikw:
            return True
        if npn and ipn and npn == ipn:
            return True
    return False


# ──── REST API ────────────────────────────────────────────


class AddRequest(BaseModel):
    keyword_jp: Optional[str] = None
    product_name: Optional[str] = None
    reason: Optional[str] = None
    source: str = "manual"


@router.get("/api/blacklist")
async def list_blacklist() -> dict:
    items = await _load_blacklist()
    # 최신 순
    items.sort(key=lambda x: x.get("added_at") or "", reverse=True)
    return {"items": items, "total": len(items)}


@router.post("/api/blacklist/add")
async def add_blacklist(req: AddRequest) -> dict:
    if not (req.keyword_jp or req.product_name):
        raise HTTPException(400, "keyword_jp 또는 product_name 중 하나 이상 필수")
    items = await _load_blacklist()
    # 중복 체크
    nkw = _normalize(req.keyword_jp)
    npn = _normalize(req.product_name)
    for it in items:
        ikw = _normalize(it.get("keyword_jp"))
        ipn = _normalize(it.get("product_name"))
        if nkw and ikw and nkw == ikw:
            return {"added": False, "reason": "이미 블랙리스트 (keyword_jp)", "id": it.get("id")}
        if npn and ipn and npn == ipn:
            return {"added": False, "reason": "이미 블랙리스트 (product_name)", "id": it.get("id")}
    new_item = {
        "id": uuid4().hex[:12],
        "keyword_jp": req.keyword_jp or "",
        "product_name": req.product_name or "",
        "reason": req.reason or "",
        "added_at": datetime.utcnow().isoformat(),
        "source": req.source,
    }
    items.append(new_item)
    await _save_blacklist(items)
    logger.info(f"[blacklist] 추가: {new_item}")
    return {"added": True, "item": new_item, "total": len(items)}


@router.delete("/api/blacklist/{item_id}")
async def remove_blacklist(item_id: str) -> dict:
    items = await _load_blacklist()
    before = len(items)
    items = [it for it in items if it.get("id") != item_id]
    after = len(items)
    if before == after:
        raise HTTPException(404, f"블랙리스트 항목 없음: {item_id}")
    await _save_blacklist(items)
    logger.info(f"[blacklist] 삭제: {item_id}")
    return {"removed": True, "id": item_id, "total": after}


@router.post("/api/blacklist/check")
async def check_blacklist(req: AddRequest) -> dict:
    """수동 진단용 — 매칭 여부 반환."""
    matched = await is_blacklisted(
        keyword_jp=req.keyword_jp or "",
        product_name=req.product_name or "",
    )
    return {"blacklisted": matched}


class BatchCheckRequest(BaseModel):
    items: list[AddRequest]


@router.post("/api/blacklist/check-batch")
async def check_batch(req: BatchCheckRequest) -> dict:
    """O (5/3) 배치 매칭 체크 — 프론트 (시트로 보내기) 가 한번에 N개 검증.

    응답 results 의 인덱스 = 입력 items 인덱스. blacklisted=true 인 항목은
    호출자가 시트 추가 전 필터링.
    """
    items_bl = await _load_blacklist()
    nset_kw = {_normalize(it.get("keyword_jp")) for it in items_bl if it.get("keyword_jp")}
    nset_pn = {_normalize(it.get("product_name")) for it in items_bl if it.get("product_name")}
    nset_kw.discard("")
    nset_pn.discard("")

    results = []
    for it in req.items:
        nkw = _normalize(it.keyword_jp or "")
        npn = _normalize(it.product_name or "")
        blocked = (bool(nkw) and nkw in nset_kw) or (bool(npn) and npn in nset_pn)
        results.append({
            "keyword_jp": it.keyword_jp,
            "product_name": it.product_name,
            "blacklisted": blocked,
        })
    return {"results": results, "total": len(results), "blocked": sum(1 for r in results if r["blacklisted"])}
