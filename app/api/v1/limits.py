import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.limit import LimitCreate, LimitResponse, LimitUpdate
from app.services import limits as limits_service

router = APIRouter(prefix="/limits")


@router.get("", response_model=list[LimitResponse])
async def list_limits(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await limits_service.list_limits(user, db)


@router.post("", response_model=LimitResponse, status_code=201)
async def create_limit(
    data: LimitCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await limits_service.create_limit(data, user, db)


@router.patch("/{limit_id}", response_model=LimitResponse)
async def update_limit(
    limit_id: uuid.UUID,
    data: LimitUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await limits_service.update_limit(limit_id, data, user, db)


@router.delete("/{limit_id}", status_code=204)
async def delete_limit(
    limit_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await limits_service.delete_limit(limit_id, user, db)
