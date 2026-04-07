import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LimitCreate(BaseModel):
    category_id: uuid.UUID
    amount: float = Field(gt=0)
    period: str = Field(default="month", pattern="^(month|week)$")


class LimitUpdate(BaseModel):
    amount: float | None = Field(default=None, gt=0)
    period: str | None = Field(default=None, pattern="^(month|week)$")


class LimitResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    amount: float
    period: str
    spent: float = 0.0       # сколько потрачено за текущий период
    created_at: datetime

    model_config = {"from_attributes": True}
