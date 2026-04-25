import uuid
from datetime import UTC, date as Date, datetime
from decimal import Decimal

import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.transaction import (
    TransactionCreate,
    TransactionListResponse,
    TransactionResponse,
    TransactionStatsResponse,
    TransactionUpdate,
)
from app.services import transactions as tx_service
from app.services.subscriptions import is_effective_pro

# Free users see only the current month and the 5 largest categories —
# deeper history and the full breakdown are Pro perks.
FREE_STATS_TOP_CATEGORIES = 5

router = APIRouter(prefix="/transactions")


@router.post("", response_model=TransactionResponse, status_code=201)
async def create_transaction(
    data: TransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await tx_service.create_transaction(data, user, db)


@router.get("/stats", response_model=TransactionStatsResponse)
async def get_stats(
    date_from: Date | None = Query(None),
    date_to: Date | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Статистика: суммы доходов/расходов, баланс, разбивка по категориям.

    Free users are restricted to the current calendar month and see only
    the top-5 categories. Requests for older data return 403.
    """
    if not is_effective_pro(user.subscription):
        month_start = datetime.now(UTC).date().replace(day=1)
        if date_from is None:
            # Default Free to current month so UI that doesn't pass dates
            # still gets a useful response.
            date_from = month_start
        elif date_from < month_start:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Сравнение по месяцам доступно в Pro",
            )

    stats = await tx_service.get_stats(
        user, db, date_from=date_from, date_to=date_to,
    )

    if not is_effective_pro(user.subscription):
        stats.income_by_category = stats.income_by_category[:FREE_STATS_TOP_CATEGORIES]
        stats.expense_by_category = stats.expense_by_category[:FREE_STATS_TOP_CATEGORIES]

    return stats


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    type: str | None = Query(None, pattern="^(expense|income)$"),
    date_from: Date | None = Query(None),
    date_to: Date | None = Query(None),
    category_id: uuid.UUID | None = Query(None),
    amount_min: Decimal | None = Query(None, gt=0),
    amount_max: Decimal | None = Query(None, gt=0),
    search: str | None = Query(None, max_length=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await tx_service.get_transactions(
        user, db,
        skip=skip,
        limit=limit,
        type_filter=type,
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        amount_min=amount_min,
        amount_max=amount_max,
        search=search,
    )


@router.get("/export")
async def export_transactions(
    date_from: Date | None = Query(None),
    date_to: Date | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Экспорт транзакций в CSV.

    Free: текущий месяц (если `date_from` не передан — авто-подстановка;
    более ранняя дата → 403 «Plus»). Plus: любой период.

    Must stay above `/{tx_id}` — otherwise FastAPI matches `export` as a UUID
    path param and returns 422 instead of hitting this handler.
    """
    if not is_effective_pro(user.subscription):
        month_start = datetime.now(UTC).date().replace(day=1)
        if date_from is None:
            date_from = month_start
        elif date_from < month_start:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Экспорт за прошлые периоды доступен в Plus",
            )

    csv_content = await tx_service.export_csv(user, db, date_from=date_from, date_to=date_to)
    filename = f"transactions_{user.id}.csv"
    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{tx_id}", response_model=TransactionResponse)
async def get_transaction(
    tx_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await tx_service.get_transaction(tx_id, user, db)


@router.patch("/{tx_id}", response_model=TransactionResponse)
async def update_transaction(
    tx_id: uuid.UUID,
    data: TransactionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await tx_service.update_transaction(tx_id, data, user, db)


@router.post("/{tx_id}/restore", response_model=TransactionResponse)
async def restore_transaction(
    tx_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Восстановить удалённую транзакцию."""
    return await tx_service.restore_transaction(tx_id, user, db)


@router.delete("/{tx_id}", status_code=204)
async def delete_transaction(
    tx_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await tx_service.delete_transaction(tx_id, user, db)
