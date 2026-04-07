import uuid
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transaction import BudgetLimit, Transaction
from app.models.user import User
from app.schemas.limit import LimitCreate, LimitResponse, LimitUpdate


def _period_start(period: str) -> date:
    today = date.today()
    if period == "week":
        return today - timedelta(days=today.weekday())
    # month
    return today.replace(day=1)


async def _get_spent(limit: BudgetLimit, user: User, db: AsyncSession) -> float:
    start = _period_start(limit.period)
    result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.user_id == user.id,
            Transaction.category_id == limit.category_id,
            Transaction.type == "expense",
            Transaction.date >= start,
            Transaction.deleted_at.is_(None),
        )
    )
    return float(result.scalar())


async def list_limits(user: User, db: AsyncSession) -> list[LimitResponse]:
    result = await db.execute(
        select(BudgetLimit)
        .where(BudgetLimit.user_id == user.id)
        .order_by(BudgetLimit.created_at)
    )
    limits = result.scalars().all()
    out = []
    for lim in limits:
        spent = await _get_spent(lim, user, db)
        r = LimitResponse.model_validate(lim)
        r.spent = spent
        out.append(r)
    return out


async def create_limit(data: LimitCreate, user: User, db: AsyncSession) -> LimitResponse:
    # Проверяем дубликат
    existing = await db.execute(
        select(BudgetLimit).where(
            BudgetLimit.user_id == user.id,
            BudgetLimit.category_id == data.category_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Limit for this category already exists")

    lim = BudgetLimit(
        user_id=user.id,
        category_id=data.category_id,
        amount=data.amount,
        period=data.period,
    )
    db.add(lim)
    await db.commit()
    await db.refresh(lim)

    spent = await _get_spent(lim, user, db)
    r = LimitResponse.model_validate(lim)
    r.spent = spent
    return r


async def update_limit(
    limit_id: uuid.UUID, data: LimitUpdate, user: User, db: AsyncSession
) -> LimitResponse:
    lim = await db.get(BudgetLimit, limit_id)
    if not lim or lim.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Limit not found")

    if data.amount is not None:
        lim.amount = data.amount
    if data.period is not None:
        lim.period = data.period

    await db.commit()
    await db.refresh(lim)

    spent = await _get_spent(lim, user, db)
    r = LimitResponse.model_validate(lim)
    r.spent = spent
    return r


async def delete_limit(limit_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    lim = await db.get(BudgetLimit, limit_id)
    if not lim or lim.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Limit not found")
    await db.delete(lim)
    await db.commit()
