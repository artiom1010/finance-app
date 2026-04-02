import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import AuthProvider, RefreshToken, Subscription, User, UserSettings
from app.schemas.auth import AuthResponse, GoogleAuthRequest, LoginRequest, RegisterRequest, UserResponse


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _get_default_theme_id(db: AsyncSession) -> uuid.UUID:
    from sqlalchemy import text
    result = await db.execute(text("SELECT id FROM themes WHERE name = 'light' LIMIT 1"))
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="Default theme not found. Run migrations first.")
    return row[0]


def _build_auth_response(user: User, access_token: str, refresh_token: str) -> AuthResponse:
    tier = user.subscription.tier if user.subscription else "free"
    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            tier=tier,
        ),
        access_token=access_token,
        refresh_token=refresh_token,
    )


async def _create_tokens_for_user(
    user: User,
    db: AsyncSession,
    device_id: str | None = None,
) -> tuple[str, str]:
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(refresh_token),
        device_id=device_id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days),
    ))

    return access_token, refresh_token


async def _init_user_defaults(user: User, db: AsyncSession) -> None:
    theme_id = await _get_default_theme_id(db)
    db.add(UserSettings(user_id=user.id, theme_id=theme_id))
    db.add(Subscription(user_id=user.id, tier="free", status="active"))


# ── Register ──────────────────────────────────────────────────────

async def register(data: RegisterRequest, db: AsyncSession) -> AuthResponse:
    # Проверяем что email не занят
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
    )
    db.add(user)
    await db.flush()  # получаем user.id без коммита

    await _init_user_defaults(user, db)
    access_token, refresh_token = await _create_tokens_for_user(user, db)

    return _build_auth_response(user, access_token, refresh_token)


# ── Login ─────────────────────────────────────────────────────────

async def login(data: LoginRequest, db: AsyncSession) -> AuthResponse:
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    access_token, refresh_token = await _create_tokens_for_user(user, db, data.device_id)
    return _build_auth_response(user, access_token, refresh_token)


# ── Google OAuth ──────────────────────────────────────────────────

async def google_auth(data: GoogleAuthRequest, db: AsyncSession) -> AuthResponse:
    # Верифицируем токен через Google API
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": data.id_token},
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token")

    google_data = resp.json()

    if google_data.get("aud") != settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token audience mismatch")

    google_user_id = google_data["sub"]
    email = google_data.get("email", "")
    first_name = google_data.get("given_name", "User")
    last_name = google_data.get("family_name")

    # Ищем существующего пользователя по провайдеру
    result = await db.execute(
        select(AuthProvider).where(
            AuthProvider.provider == "google",
            AuthProvider.provider_user_id == google_user_id,
        )
    )
    provider = result.scalar_one_or_none()

    if provider:
        # Пользователь уже есть — просто логиним
        result = await db.execute(select(User).where(User.id == provider.user_id))
        user = result.scalar_one()
    else:
        # Новый пользователь — создаём
        # Проверяем не занят ли email другим аккаунтом
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            user = User(email=email, first_name=first_name, last_name=last_name)
            db.add(user)
            await db.flush()
            await _init_user_defaults(user, db)

        db.add(AuthProvider(
            user_id=user.id,
            provider="google",
            provider_user_id=google_user_id,
        ))

    access_token, refresh_token = await _create_tokens_for_user(user, db, data.device_id)
    return _build_auth_response(user, access_token, refresh_token)


# ── Refresh ───────────────────────────────────────────────────────

async def refresh_tokens(raw_token: str, db: AsyncSession) -> AuthResponse:
    from app.core.security import decode_token

    payload = decode_token(raw_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token or db_token.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired or revoked")

    # Ротация: отзываем старый, выдаём новый
    db_token.revoked_at = datetime.now(UTC)

    result = await db.execute(select(User).where(User.id == db_token.user_id))
    user = result.scalar_one()

    access_token, new_refresh_token = await _create_tokens_for_user(user, db, db_token.device_id)
    return _build_auth_response(user, access_token, new_refresh_token)


# ── Logout ────────────────────────────────────────────────────────

async def logout(raw_token: str, db: AsyncSession) -> None:
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    db_token = result.scalar_one_or_none()
    if db_token:
        db_token.revoked_at = datetime.now(UTC)
