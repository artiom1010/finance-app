import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.ai import AiAskRequest, AiChatResponse, AiMessageResponse, AiPromptTemplateResponse
from app.services import ai as ai_service

router = APIRouter(prefix="/ai")


@router.get("/templates", response_model=list[AiPromptTemplateResponse])
async def get_templates(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Кнопки-шаблоны вопросов (preset buttons в интерфейсе)."""
    return await ai_service.get_templates(db)


@router.get("/chat", response_model=AiChatResponse)
async def get_chat(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """История чата + счётчик запросов сегодня."""
    return await ai_service.get_chat(user, db)


@router.post("/ask", response_model=AiMessageResponse)
async def ask(
    data: AiAskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить сообщение AI советнику."""
    return await ai_service.ask(data, user, db)


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(
    message_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить отдельное сообщение из чата (soft delete)."""
    await ai_service.delete_message(message_id, user, db)


@router.delete("/chat", status_code=204)
async def clear_chat(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Очистить историю чата (soft clear — данные не удаляются)."""
    await ai_service.clear_chat(user, db)
