import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class RecurringCreate(BaseModel):
    category_id: uuid.UUID
    amount: float = Field(gt=0)
    type: str = Field(pattern="^(expense|income)$")
    frequency: str = Field(pattern="^(daily|weekly|monthly|yearly)$")
    note: str | None = Field(default=None, max_length=500)
    next_date: date


class RecurringUpdate(BaseModel):
    amount: float | None = Field(default=None, gt=0)
    frequency: str | None = Field(default=None, pattern="^(daily|weekly|monthly|yearly)$")
    note: str | None = None
    next_date: date | None = None
    is_active: bool | None = None


class RecurringResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str = ""
    category_icon: str = "💰"
    amount: float
    type: str
    frequency: str
    note: str | None
    next_date: date
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
