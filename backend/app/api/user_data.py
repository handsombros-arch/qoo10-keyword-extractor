"""범용 JSON 저장 API.

시트·관심 키워드·샵 캐시 등을 DB에 저장하여 PC 간 공유한다.
"""
import json as jsonlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_session
from app.db.models import UserData

router = APIRouter(prefix="/api/user-data", tags=["user-data"])

ALLOWED_KEYS = {
    "product_sheet",
    "margin_sheet",            # 큐텐 마진 시트 행 (PC 간 공유 + 백업)
    "margin_sheet_settings",   # 마진 시트 환율·배수·메가할인 등 설정
    "streak_freezes",          # 대시보드 등록 스트릭 freeze
    "shop_urls",               # 샵 벤치마크 URL 목록
    "interest_keywords",
    "shop_cache",
    "brand_auto_add_threshold",  # /settings 에서 조정. payload: {"value": 0.0~1.0}
    "auto_filter_categories",     # /settings 카테고리 화이트리스트. payload: {"value": ["03.뷰티&화장품", ...]}
    "auto_filter_thresholds",     # /settings 슬라이더. payload: {"competition_max": 2.0, "kr_ratio_min": 0.3, "volume_min": 40}
    "quality_thresholds",          # III-1 매칭 quality. payload: {"accept": 0.7, "review": 0.5, "desc_weight": 0.25}
    "auto_filter_category_blacklist",  # MMM-1 raw 큐텐 카테고리 blacklist. payload: {"value": ["05.디지털", ...]}
}

# 와일드카드 prefix — 날짜별 storage (시트가 read-only fetch)
_PREFIX_KEYS = (
    "last_auto_collected:",     # auto-build 결과 snapshot
    "last_match_retry:",        # HHH-1 결과
    "last_candidate_folders:",  # 후보 폴더 매핑 (folder_index/name + qoo10_url)
)


def _is_allowed(key: str) -> bool:
    return key in ALLOWED_KEYS or any(key.startswith(p) for p in _PREFIX_KEYS)


class PutRequest(BaseModel):
    data: object  # 임의의 JSON


@router.get("/{key}")
async def get_data(key: str, session: AsyncSession = Depends(get_session)):
    if not _is_allowed(key):
        raise HTTPException(400, f"허용되지 않은 키: {key}")

    result = await session.execute(select(UserData).where(UserData.key == key))
    row = result.scalar_one_or_none()
    if not row:
        return {"key": key, "data": None, "updated_at": None}

    try:
        data = jsonlib.loads(row.data) if row.data else None
    except Exception:
        data = None
    return {
        "key": row.key,
        "data": data,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.put("/{key}")
async def put_data(key: str, req: PutRequest, session: AsyncSession = Depends(get_session)):
    if not _is_allowed(key):
        raise HTTPException(400, f"허용되지 않은 키: {key}")

    payload = jsonlib.dumps(req.data, ensure_ascii=False)
    now = datetime.utcnow()

    result = await session.execute(select(UserData).where(UserData.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.data = payload
        row.updated_at = now
    else:
        session.add(UserData(key=key, data=payload, updated_at=now))

    await session.commit()
    # III-1 — quality_thresholds 변경 시 매칭 캐시 무효화
    if key == "quality_thresholds":
        try:
            from app.services.match_quality import invalidate_quality_cache
            invalidate_quality_cache()
        except Exception:
            pass
    return {"key": key, "updated_at": now.isoformat()}


@router.delete("/{key}")
async def delete_data(key: str, session: AsyncSession = Depends(get_session)):
    if not _is_allowed(key):
        raise HTTPException(400, f"허용되지 않은 키: {key}")
    from sqlalchemy import delete as sql_delete
    await session.execute(sql_delete(UserData).where(UserData.key == key))
    await session.commit()
    return {"status": "deleted"}
