import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    icon: str = Field(default="💰", max_length=10)
    color: str = Field(default="#6B7280", max_length=20)
    type: str = Field(pattern="^(expense|income|both)$")


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=10)
    color: str | None = Field(default=None, max_length=20)
    type: str | None = Field(default=None, pattern="^(expense|income|both)$")
    sort_order: int | None = Field(default=None, ge=0)


class CategoryResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None  # None = системная
    name: str
    icon: str
    color: str
    type: str
    is_active: bool
    sort_order: int

    model_config = {"from_attributes": True}
