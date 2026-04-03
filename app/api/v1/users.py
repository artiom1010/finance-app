import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.user import (
    AuthProviderResponse,
    CurrencyResponse,
    EmailChangeRequest,
    PasswordChangeRequest,
    SessionResponse,
    SubscriptionResponse,
    ThemeResponse,
    UserProfileResponse,
    UserProfileUpdate,
    UserSettingsResponse,
    UserSettingsUpdate,
)
from app.services import users as user_service

router = APIRouter(prefix="/users")


# ── Профиль ───────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfileResponse)
async def get_me(user: User = Depends(get_current_user)):
    return await user_service.get_profile(user)


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    data: UserProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await user_service.update_profile(data, user, db)


@router.post("/me/change-password", status_code=204)
async def change_password(
    data: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Смена пароля. Требует текущий пароль. Не работает для OAuth-аккаунтов."""
    await user_service.change_password(data, user, db)


@router.delete("/me", status_code=204)
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete аккаунта: деактивирует пользователя и отзывает все сессии."""
    await user_service.delete_account(user, db)


# ── Настройки ─────────────────────────────────────────────────────

@router.get("/me/settings", response_model=UserSettingsResponse)
async def get_my_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await user_service.get_settings(user, db)


@router.patch("/me/settings", response_model=UserSettingsResponse)
async def update_my_settings(
    data: UserSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await user_service.update_settings(data, user, db)


# ── Подписка ──────────────────────────────────────────────────────

@router.get("/me/subscription", response_model=SubscriptionResponse)
async def get_my_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Текущий план подписки, статус, магазин (App Store / Google Play)."""
    return await user_service.get_subscription(user, db)


# ── OAuth провайдеры ───────────────────────────────────────────────

@router.get("/me/providers", response_model=list[AuthProviderResponse])
async def list_providers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список подключённых OAuth провайдеров (google, apple)."""
    return await user_service.list_providers(user, db)


@router.delete("/me/providers/{provider}", status_code=204)
async def disconnect_provider(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отключить OAuth провайдер. Нельзя отключить последний способ входа без пароля."""
    await user_service.disconnect_provider(provider, user, db)


# ── Сессии ────────────────────────────────────────────────────────

@router.get("/me/sessions", response_model=list[SessionResponse])
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список активных сессий (устройств). Показывает только неотозванные и неистёкшие токены."""
    return await user_service.list_sessions(user, db)


@router.delete("/me/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отозвать конкретную сессию (выйти с устройства)."""
    await user_service.revoke_session(session_id, user, db)


# ── Email ─────────────────────────────────────────────────────────

@router.post("/me/change-email", response_model=UserProfileResponse)
async def change_email(
    data: EmailChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Смена email. Требует текущий пароль. Только для аккаунтов с паролем."""
    return await user_service.change_email(data, user, db)


# ── Справочники ───────────────────────────────────────────────────

@router.get("/currencies", response_model=list[CurrencyResponse])
async def get_currencies(db: AsyncSession = Depends(get_db)):
    """Список доступных валют для настроек пользователя."""
    return await user_service.list_currencies(db)


@router.get("/themes", response_model=list[ThemeResponse])
async def get_themes(db: AsyncSession = Depends(get_db)):
    """Список доступных тем оформления."""
    return await user_service.list_themes(db)
