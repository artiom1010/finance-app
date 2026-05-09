import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _validate_thresholds(v: list[int]) -> list[int]:
    if len(v) != 3:
        raise ValueError("Нужно ровно 3 порога")
    for t in v:
        if t < 1 or t > 200:
            raise ValueError("Каждый порог — от 1 до 200%")
    s = sorted(v)
    if s != list(v) and s != v:
        # tolerate any order on input but normalise to sorted ascending so
        # the client and the alert-check loop have the same ordering.
        return s
    return s


class LimitCreate(BaseModel):
    category_id: uuid.UUID
    amount: float = Field(gt=0)
    period: str = Field(default="month", pattern="^(month|week)$")
    alert_thresholds: list[int] = Field(default_factory=lambda: [50, 75, 100])

    @field_validator("alert_thresholds")
    @classmethod
    def _check_thresholds(cls, v: list[int]) -> list[int]:
        return _validate_thresholds(v)


class LimitUpdate(BaseModel):
    amount: float | None = Field(default=None, gt=0)
    period: str | None = Field(default=None, pattern="^(month|week)$")
    alert_thresholds: list[int] | None = None

    @field_validator("alert_thresholds")
    @classmethod
    def _check_thresholds(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        return _validate_thresholds(v)


class LimitResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    amount: float
    period: str
    alert_thresholds: list[int]
    spent: float = 0.0       # сколько потрачено за текущий период
    created_at: datetime

    model_config = {"from_attributes": True}
