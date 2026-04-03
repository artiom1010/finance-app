import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AiPromptTemplateResponse(BaseModel):
    id: uuid.UUID
    label: str
    prompt: str
    icon: str
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class AiMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tokens_used: int | None
    created_at: datetime
    prompt_template_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class AiAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    prompt_template_id: uuid.UUID | None = None


class AiChatResponse(BaseModel):
    messages: list[AiMessageResponse]
    requests_today: int
    daily_limit: int  # 5 для free, -1 для pro (безлимит)
