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
    "interest_keywords",
    "shop_cache",
    "brand_auto_add_threshold",  # /settings 에서 조정. payload: {"value": 0.0~1.0}
    "auto_filter_categories",     # /settings 카테고리 화이트리스트. payload: {"value": ["03.뷰티&화장품", ...]}
}


class PutRequest(BaseModel):
    data: object  # 임의의 JSON


@router.get("/{key}")
async def get_data(key: str, session: AsyncSession = Depends(get_session)):
    if key not in ALLOWED_KEYS:
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
    if key not in ALLOWED_KEYS:
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
    return {"key": key, "updated_at": now.isoformat()}


@router.delete("/{key}")
async def delete_data(key: str, session: AsyncSession = Depends(get_session)):
    if key not in ALLOWED_KEYS:
        raise HTTPException(400, f"허용되지 않은 키: {key}")
    from sqlalchemy import delete as sql_delete
    await session.execute(sql_delete(UserData).where(UserData.key == key))
    await session.commit()
    return {"status": "deleted"}
