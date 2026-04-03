import uuid
from datetime import date as Date
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class TransactionCreate(BaseModel):
    category_id: uuid.UUID
    amount: Decimal = Field(gt=0, decimal_places=2)
    type: str = Field(pattern="^(expense|income)$")
    note: str | None = Field(default=None, max_length=500)
    date: Date


class TransactionUpdate(BaseModel):
    category_id: uuid.UUID | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    type: str | None = Field(default=None, pattern="^(expense|income)$")
    note: str | None = Field(default=None, max_length=500)
    date: Date | None = None


class CategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    icon: str
    color: str
    type: str

    model_config = {"from_attributes": True}


class TransactionResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    category: CategoryResponse
    amount: Decimal
    type: str
    note: str | None
    date: Date
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int


class CategoryStatsItem(BaseModel):
    category_id: uuid.UUID
    category_name: str
    category_icon: str
    total: Decimal
    count: int


class TransactionStatsResponse(BaseModel):
    income_total: Decimal
    expense_total: Decimal
    balance: Decimal
    income_by_category: list[CategoryStatsItem]
    expense_by_category: list[CategoryStatsItem]
    period_start: Date | None
    period_end: Date | None
