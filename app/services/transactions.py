import uuid
from datetime import UTC, datetime
from datetime import date as Date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.telegram import fmt_first_transaction, notify
from app.models.transaction import Category, Transaction
from app.models.user import User
from app.schemas.transaction import (
    CategoryStatsItem,
    TransactionCreate,
    TransactionListResponse,
    TransactionResponse,
    TransactionStatsResponse,
    TransactionUpdate,
)


async def _validate_category(category_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    """Категория должна быть системной (user_id IS NULL) или принадлежать текущему пользователю."""
    cat = await db.get(Category, category_id)
    if not cat or not cat.is_active or (cat.user_id is not None and cat.user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")


async def create_transaction(data: TransactionCreate, user: User, db: AsyncSession) -> TransactionResponse:
    await _validate_category(data.category_id, user, db)

    count_result = await db.execute(
        select(func.count()).select_from(Transaction).where(
            Transaction.user_id == user.id, Transaction.deleted_at.is_(None)
        )
    )
    is_first = count_result.scalar() == 0

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

    if is_first:
        cat_name = tx.category.name if tx.category else "—"
        await notify(fmt_first_transaction(user.email, data.amount, data.type, cat_name))

    return TransactionResponse.model_validate(tx)


async def get_transactions(
    user: User,
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    type_filter: str | None = None,
    date_from: Date | None = None,
    date_to: Date | None = None,
    category_id: uuid.UUID | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    search: str | None = None,
) -> TransactionListResponse:
    base_where = [Transaction.user_id == user.id, Transaction.deleted_at.is_(None)]

    if type_filter:
        base_where.append(Transaction.type == type_filter)
    if date_from:
        base_where.append(Transaction.date >= date_from)
    if date_to:
        base_where.append(Transaction.date <= date_to)
    if category_id:
        base_where.append(Transaction.category_id == category_id)
    if amount_min is not None:
        base_where.append(Transaction.amount >= amount_min)
    if amount_max is not None:
        base_where.append(Transaction.amount <= amount_max)
    if search:
        base_where.append(Transaction.note.ilike(f"%{search}%"))

    total_result = await db.execute(
        select(func.count()).select_from(
            select(Transaction).where(*base_where).subquery()
        )
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(Transaction)
        .where(*base_where)
        .options(selectinload(Transaction.category))
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
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

    if data.category_id is not None:
        await _validate_category(data.category_id, user, db)

    # exclude_unset=True: различаем "не передано" от "явно передан null" (для очистки note)
    for field, value in data.model_dump(exclude_unset=True).items():
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


async def restore_transaction(tx_id: uuid.UUID, user: User, db: AsyncSession) -> TransactionResponse:
    result = await db.execute(
        select(Transaction)
        .where(
            Transaction.id == tx_id,
            Transaction.user_id == user.id,
            Transaction.deleted_at.is_not(None),
        )
        .options(selectinload(Transaction.category))
    )
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deleted transaction not found")
    tx.deleted_at = None
    await db.flush()
    return TransactionResponse.model_validate(tx)


async def get_stats(
    user: User,
    db: AsyncSession,
    date_from: Date | None = None,
    date_to: Date | None = None,
) -> TransactionStatsResponse:
    base_where = [Transaction.user_id == user.id, Transaction.deleted_at.is_(None)]
    if date_from:
        base_where.append(Transaction.date >= date_from)
    if date_to:
        base_where.append(Transaction.date <= date_to)

    # Суммы по типу
    totals_result = await db.execute(
        select(Transaction.type, func.sum(Transaction.amount).label("total"))
        .where(*base_where)
        .group_by(Transaction.type)
    )
    totals = {row.type: Decimal(row.total or 0) for row in totals_result}
    income_total = totals.get("income", Decimal("0"))
    expense_total = totals.get("expense", Decimal("0"))

    # Разбивка по категориям
    by_cat_result = await db.execute(
        select(
            Transaction.type,
            Transaction.category_id,
            Category.name.label("cat_name"),
            Category.icon.label("cat_icon"),
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        )
        .join(Category, Transaction.category_id == Category.id)
        .where(*base_where)
        .group_by(Transaction.type, Transaction.category_id, Category.name, Category.icon)
        .order_by(func.sum(Transaction.amount).desc())
    )

    income_by_cat: list[CategoryStatsItem] = []
    expense_by_cat: list[CategoryStatsItem] = []
    for row in by_cat_result:
        item = CategoryStatsItem(
            category_id=row.category_id,
            category_name=row.cat_name,
            category_icon=row.cat_icon,
            total=Decimal(row.total),
            count=row.count,
        )
        if row.type == "income":
            income_by_cat.append(item)
        else:
            expense_by_cat.append(item)

    return TransactionStatsResponse(
        income_total=income_total,
        expense_total=expense_total,
        balance=income_total - expense_total,
        income_by_category=income_by_cat,
        expense_by_category=expense_by_cat,
        period_start=date_from,
        period_end=date_to,
    )
