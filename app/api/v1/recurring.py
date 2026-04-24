import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_pro_user, get_current_user
from app.models.user import User
from app.schemas.recurring import RecurringCreate, RecurringResponse, RecurringUpdate
from app.services import recurring as rec_service

router = APIRouter(prefix="/recurring")


@router.get("", response_model=list[RecurringResponse])
async def list_recurring(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recurring rules. Open to Free so the UI can show an empty state
    with an upgrade CTA instead of a bare 403."""
    return await rec_service.list_recurring(user, db)


@router.post("", response_model=RecurringResponse, status_code=201)
async def create_recurring(
    data: RecurringCreate,
    user: User = Depends(get_current_pro_user),
    db: AsyncSession = Depends(get_db),
):
    return await rec_service.create_recurring(data, user, db)


@router.patch("/{rec_id}", response_model=RecurringResponse)
async def update_recurring(
    rec_id: uuid.UUID,
    data: RecurringUpdate,
    user: User = Depends(get_current_pro_user),
    db: AsyncSession = Depends(get_db),
):
    return await rec_service.update_recurring(rec_id, data, user, db)


@router.delete("/{rec_id}", status_code=204)
async def delete_recurring(
    rec_id: uuid.UUID,
    user: User = Depends(get_current_pro_user),
    db: AsyncSession = Depends(get_db),
):
    await rec_service.delete_recurring(rec_id, user, db)
