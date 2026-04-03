import uuid
from datetime import datetime

from pydantic import BaseModel


class CategoryCreate(BaseModel):
    name: str
    icon: str = "💰"
    color: str = "#6B7280"
    type: str  # expense | income | both


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
