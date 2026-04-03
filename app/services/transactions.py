import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import TransactionCreate, TransactionListResponse, TransactionResponse, TransactionUpdate


async def create_transaction(data: TransactionCreate, user: User, db: AsyncSession) -> TransactionResponse:
    tx = Transaction(
        user_id=user.id,
        category_id=data.category_id,
        amount=data.amount,
        type=data.type,
        note=data.note,
        date=data.date,
    )
    db.add(tx)
    await db.flush()

    await db.refresh(tx, ["category"])
    return TransactionResponse.model_validate(tx)


async def get_transactions(
    user: User,
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    type_filter: str | None = None,
) -> TransactionListResponse:
    query = (
        select(Transaction)
        .where(Transaction.user_id == user.id, Transaction.deleted_at.is_(None))
        .options(selectinload(Transaction.category))
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
    )

    if type_filter:
        query = query.where(Transaction.type == type_filter)

    count_query = select(func.count()).select_from(
        select(Transaction)
        .where(Transaction.user_id == user.id, Transaction.deleted_at.is_(None))
        .subquery()
    )
    if type_filter:
        count_query = select(func.count()).select_from(
            select(Transaction)
            .where(Transaction.user_id == user.id, Transaction.deleted_at.is_(None), Transaction.type == type_filter)
            .subquery()
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    result = await db.execute(query.offset(skip).limit(limit))
    transactions = result.scalars().all()

    return TransactionListResponse(
        items=[TransactionResponse.model_validate(tx) for tx in transactions],
        total=total,
    )


async def get_transaction(tx_id: uuid.UUID, user: User, db: AsyncSession) -> TransactionResponse:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.id == tx_id, Transaction.user_id == user.id, Transaction.deleted_at.is_(None))
        .options(selectinload(Transaction.category))
    )
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return TransactionResponse.model_validate(tx)


async def update_transaction(tx_id: uuid.UUID, data: TransactionUpdate, user: User, db: AsyncSession) -> TransactionResponse:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.id == tx_id, Transaction.user_id == user.id, Transaction.deleted_at.is_(None))
        .options(selectinload(Transaction.category))
    )
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(tx, field, value)

    await db.flush()
    await db.refresh(tx, ["category"])
    return TransactionResponse.model_validate(tx)


async def delete_transaction(tx_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.id == tx_id, Transaction.user_id == user.id, Transaction.deleted_at.is_(None))
    )
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    tx.deleted_at = datetime.now(UTC)
