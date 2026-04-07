import uuid
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transaction import Category, RecurringTransaction, Transaction
from app.models.user import User
from app.schemas.recurring import RecurringCreate, RecurringResponse, RecurringUpdate


def _next_occurrence(current: date, frequency: str) -> date:
    if frequency == "daily":
        return current + timedelta(days=1)
    if frequency == "weekly":
        return current + timedelta(weeks=1)
    if frequency == "monthly":
        return current + relativedelta(months=1)
    if frequency == "yearly":
        return current + relativedelta(years=1)
    return current + timedelta(days=30)


def _to_response(rec: RecurringTransaction) -> RecurringResponse:
    r = RecurringResponse.model_validate(rec)
    if rec.category:
        r.category_name = rec.category.name
        r.category_icon = rec.category.icon
    return r


async def list_recurring(user: User, db: AsyncSession) -> list[RecurringResponse]:
    result = await db.execute(
        select(RecurringTransaction)
        .where(RecurringTransaction.user_id == user.id)
        .options(selectinload(RecurringTransaction.category))
        .order_by(RecurringTransaction.next_date)
    )
    return [_to_response(r) for r in result.scalars().all()]


async def create_recurring(
    data: RecurringCreate, user: User, db: AsyncSession
) -> RecurringResponse:
    cat = await db.get(Category, data.category_id)
    if not cat or not cat.is_active or (cat.user_id is not None and cat.user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    rec = RecurringTransaction(
        user_id=user.id,
        category_id=data.category_id,
        amount=data.amount,
        type=data.type,
        frequency=data.frequency,
        note=data.note,
        next_date=data.next_date,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec, ["category"])
    return _to_response(rec)


async def update_recurring(
    rec_id: uuid.UUID, data: RecurringUpdate, user: User, db: AsyncSession
) -> RecurringResponse:
    result = await db.execute(
        select(RecurringTransaction)
        .where(RecurringTransaction.id == rec_id, RecurringTransaction.user_id == user.id)
        .options(selectinload(RecurringTransaction.category))
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rec, field, value)

    await db.commit()
    await db.refresh(rec, ["category"])
    return _to_response(rec)


async def delete_recurring(rec_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    result = await db.execute(
        select(RecurringTransaction)
        .where(RecurringTransaction.id == rec_id, RecurringTransaction.user_id == user.id)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await db.delete(rec)
    await db.commit()


async def apply_due(db: AsyncSession) -> int:
    """Создаёт транзакции для всех активных записей с next_date <= today.
    Вызывается по расписанию (cron / background task).
    Возвращает количество созданных транзакций."""
    today = date.today()
    result = await db.execute(
        select(RecurringTransaction)
        .where(
            RecurringTransaction.is_active == True,  # noqa: E712
            RecurringTransaction.next_date <= today,
        )
        .options(selectinload(RecurringTransaction.category))
    )
    due = result.scalars().all()
    count = 0
    for rec in due:
        tx = Transaction(
            user_id=rec.user_id,
            category_id=rec.category_id,
            amount=rec.amount,
            type=rec.type,
            note=rec.note,
            date=rec.next_date,
        )
        db.add(tx)
        rec.next_date = _next_occurrence(rec.next_date, rec.frequency)
        count += 1
    if count:
        await db.commit()
    return count
