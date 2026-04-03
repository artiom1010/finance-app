import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import AuthProvider, Currency, RefreshToken, Subscription, Theme, User, UserSettings
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


async def get_profile(user: User) -> UserProfileResponse:
    tier = user.subscription.tier if user.subscription else "free"
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        tier=tier,
    )


async def update_profile(data: UserProfileUpdate, user: User, db: AsyncSession) -> UserProfileResponse:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.flush()
    return await get_profile(user)


async def get_settings(user: User, db: AsyncSession) -> UserSettingsResponse:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    settings_obj = result.scalar_one_or_none()
    if not settings_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settings not found")
    return UserSettingsResponse.model_validate(settings_obj)


async def update_settings(data: UserSettingsUpdate, user: User, db: AsyncSession) -> UserSettingsResponse:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    settings_obj = result.scalar_one_or_none()
    if not settings_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settings not found")

    updates = data.model_dump(exclude_unset=True)

    if "currency_code" in updates:
        cur = await db.get(Currency, updates["currency_code"])
        if not cur:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Currency not found")

    if "theme_id" in updates:
        theme = await db.get(Theme, updates["theme_id"])
        if not theme:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Theme not found")

    for field, value in updates.items():
        setattr(settings_obj, field, value)

    await db.flush()
    await db.refresh(settings_obj)
    return UserSettingsResponse.model_validate(settings_obj)


async def change_password(data: PasswordChangeRequest, user: User, db: AsyncSession) -> None:
    if not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account uses social login, no password set",
        )
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    user.password_hash = hash_password(data.new_password)
    await db.flush()


async def delete_account(user: User, db: AsyncSession) -> None:
    """Soft-delete: деактивируем аккаунт и отзываем все refresh токены."""
    user.is_active = False
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    tokens = result.scalars().all()
    now = datetime.now(UTC)
    for token in tokens:
        token.revoked_at = now
    await db.flush()


async def get_subscription(user: User, db: AsyncSession) -> SubscriptionResponse:
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    return SubscriptionResponse.model_validate(sub)


async def list_providers(user: User, db: AsyncSession) -> list[AuthProviderResponse]:
    result = await db.execute(
        select(AuthProvider).where(AuthProvider.user_id == user.id).order_by(AuthProvider.created_at)
    )
    return [AuthProviderResponse.model_validate(p) for p in result.scalars().all()]


async def disconnect_provider(provider: str, user: User, db: AsyncSession) -> None:
    result = await db.execute(
        select(AuthProvider).where(
            AuthProvider.user_id == user.id,
            AuthProvider.provider == provider,
        )
    )
    prov = result.scalar_one_or_none()
    if not prov:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not connected")

    # Нельзя отключить единственный способ входа если нет пароля
    if not user.password_hash:
        count_result = await db.execute(
            select(func.count()).select_from(AuthProvider).where(AuthProvider.user_id == user.id)
        )
        if count_result.scalar() <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot disconnect the only login method. Set a password first.",
            )

    await db.delete(prov)
    await db.flush()


async def list_sessions(user: User, db: AsyncSession) -> list[SessionResponse]:
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(UTC),
        ).order_by(RefreshToken.created_at.desc())
    )
    return [SessionResponse.model_validate(s) for s in result.scalars().all()]


async def revoke_session(session_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.id == session_id,
            RefreshToken.user_id == user.id,
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    token.revoked_at = datetime.now(UTC)
    await db.flush()


async def change_email(data: EmailChangeRequest, user: User, db: AsyncSession) -> UserProfileResponse:
    if not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account uses social login only. Add a password before changing email.",
        )
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    new_email = data.new_email.lower().strip()

    existing = await db.execute(select(User).where(User.email == new_email, User.id != user.id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

    user.email = new_email
    await db.flush()
    return await get_profile(user)


async def list_currencies(db: AsyncSession) -> list[CurrencyResponse]:
    result = await db.execute(select(Currency).order_by(Currency.code))
    currencies = result.scalars().all()
    return [CurrencyResponse.model_validate(c) for c in currencies]


async def list_themes(db: AsyncSession) -> list[ThemeResponse]:
    result = await db.execute(select(Theme).order_by(Theme.name))
    themes = result.scalars().all()
    return [ThemeResponse.model_validate(t) for t in themes]
