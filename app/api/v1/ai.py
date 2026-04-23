from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.ai import (
    AiCommandRequest,
    AiCommandResponse,
    AiTemplateDescriptor,
    AiUsageResponse,
)
from app.services import ai as ai_service

router = APIRouter(prefix="/ai")
limiter = Limiter(key_func=get_remote_address)


@router.get("/templates", response_model=list[AiTemplateDescriptor])
async def get_templates(user: User = Depends(get_current_user)):
    """Static list of the three available AI commands for the client UI."""
    return ai_service.list_templates()


@router.get("/usage", response_model=AiUsageResponse)
async def get_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Badge data for the AI screen: used/limit and per-command cache freshness."""
    return await ai_service.get_usage(user, db)


@router.post("/command", response_model=AiCommandResponse)
@limiter.limit("10/minute")
async def run_command(
    request: Request,
    data: AiCommandRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute one of the three fixed AI commands.

    Rate-limited at the HTTP edge (slowapi) to defend against single-IP DoS.
    Business-level daily quotas (Free=1, Pro=3) live in the service layer.
    """
    return await ai_service.run_command(data.command, user, db)
