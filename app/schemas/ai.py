import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


AiCommand = Literal["headline", "overshoot", "cuts"]


class AiCommandRequest(BaseModel):
    command: AiCommand


QuotaPeriod = Literal["day", "week"]


class AiCommandResponse(BaseModel):
    command: AiCommand
    text: str
    cached: bool
    tokens_used: int
    used: int            # commands consumed in the current quota window
    limit: int           # 1 for free, 3 for pro
    period: QuotaPeriod  # "week" for free, "day" for pro
    generated_at: datetime


class AiUsageResponse(BaseModel):
    used: int
    limit: int
    period: QuotaPeriod
    cached: dict[str, datetime | None]  # {command: last_generated_at}


# Kept for `GET /ai/templates` — static info describing the 3 commands.
class AiTemplateDescriptor(BaseModel):
    id: AiCommand
    title: str
    subtitle: str
    icon: str
