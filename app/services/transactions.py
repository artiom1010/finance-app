import csv
import io
import uuid
from datetime import UTC, datetime
from datetime import date as Date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.telegram import fmt_first_transaction, notify
from app.models.transaction import BudgetLimit, Category, Transaction
from app.models.user import User
from app.schemas.transaction import (
    CategoryStatsItem,
    MonthlySummaryItem,
    TransactionCreate,
    TransactionListResponse,
    TransactionResponse,
    TransactionStatsResponse,
    TransactionUpdate,
    TriggeredAlert,
)
from app.services.limits import _get_spent


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

    triggered = await _check_limit_thresholds(tx, data, user, db)

    response = TransactionResponse.model_validate(tx)
    response.triggered_alerts = triggered
    return response


async def _check_limit_thresholds(
    tx: Transaction, data: TransactionCreate, user: User, db: AsyncSession,
) -> list[TriggeredAlert]:
    """Return thresholds that this transaction just pushed `spent` past.

    Only expense transactions trigger alerts — incomes and category-less
    cases produce an empty list. Detection is transition-based: for each
    configured threshold `t`, fire if `spent_before < limit*t/100 <= spent_after`.
    No "already-fired" persistence — natural transitivity covers it.
    """
    if data.type != "expense":
        return []

    limit_row = await db.execute(
        select(BudgetLimit).where(
            BudgetLimit.user_id == user.id,
            BudgetLimit.category_id == data.category_id,
        )
    )
    limit = limit_row.scalar_one_or_none()
    if limit is None:
        return []

    spent_after = Decimal(str(await _get_spent(limit, user, db)))
    spent_before = spent_after - Decimal(data.amount)
    limit_amount = Decimal(str(limit.amount))
    cat_name = tx.category.name if tx.category else "—"

    triggered: list[TriggeredAlert] = []
    for t in (limit.alert_thresholds or []):
        threshold_amount = limit_amount * Decimal(t) / Decimal(100)
        if spent_before < threshold_amount <= spent_after:
            triggered.append(TriggeredAlert(
                limit_id=limit.id,
                category_name=cat_name,
                threshold=int(t),
                spent=spent_after,
                amount=limit_amount,
            ))
    return triggered


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


async def get_monthly_summary(
    user: User,
    db: AsyncSession,
    end_year: int,
    end_month: int,
    months: int,
) -> list[MonthlySummaryItem]:
    """Income/expense totals for `months` consecutive months ending at
    (end_year, end_month). Months with no transactions are still returned
    with zero totals so the UI can render a stable bar count.
    """
    # Walk back `months - 1` from the end to find the start.
    sy, sm = end_year, end_month - (months - 1)
    while sm <= 0:
        sm += 12
        sy -= 1
    start_date = Date(sy, sm, 1)
    if end_month == 12:
        end_exclusive = Date(end_year + 1, 1, 1)
    else:
        end_exclusive = Date(end_year, end_month + 1, 1)

    rows = await db.execute(
        select(
            func.extract("year", Transaction.date).label("y"),
            func.extract("month", Transaction.date).label("m"),
            Transaction.type,
            func.sum(Transaction.amount).label("total"),
        )
        .where(
            Transaction.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.date >= start_date,
            Transaction.date < end_exclusive,
        )
        .group_by("y", "m", Transaction.type)
    )

    buckets: dict[tuple[int, int], dict[str, Decimal]] = {}
    for r in rows:
        key = (int(r.y), int(r.m))
        bucket = buckets.setdefault(
            key, {"income": Decimal("0"), "expense": Decimal("0")}
        )
        bucket[r.type] = Decimal(r.total or 0)

    out: list[MonthlySummaryItem] = []
    y, m = sy, sm
    for _ in range(months):
        b = buckets.get((y, m), {"income": Decimal("0"), "expense": Decimal("0")})
        out.append(MonthlySummaryItem(
            year=y, month=m, income=b["income"], expense=b["expense"],
        ))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


async def export_csv(
    user: User,
    db: AsyncSession,
    date_from: Date | None = None,
    date_to: Date | None = None,
) -> str:
    """Возвращает CSV-строку всех транзакций пользователя."""
    where = [Transaction.user_id == user.id, Transaction.deleted_at.is_(None)]
    if date_from:
        where.append(Transaction.date >= date_from)
    if date_to:
        where.append(Transaction.date <= date_to)

    result = await db.execute(
        select(Transaction)
        .where(*where)
        .options(selectinload(Transaction.category))
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
    )
    transactions = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "type", "amount", "category", "note"])
    for tx in transactions:
        writer.writerow([
            tx.date.isoformat(),
            tx.type,
            str(tx.amount),
            tx.category.name if tx.category else "",
            tx.note or "",
        ])
    return output.getvalue()
