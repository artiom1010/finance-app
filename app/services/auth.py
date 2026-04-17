import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.telegram import fmt_login, fmt_register, notify
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import AuthProvider, RefreshToken, Subscription, User, UserSettings
from app.schemas.auth import AppleAuthRequest, AuthResponse, GoogleAuthRequest, LoginRequest, RegisterRequest, UserResponse


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _get_default_theme_id(db: AsyncSession) -> uuid.UUID:
    from sqlalchemy import text
    result = await db.execute(text("SELECT id FROM themes WHERE name = 'light' LIMIT 1"))
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="Registration temporarily unavailable")
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


async def _cleanup_old_tokens(user_id: uuid.UUID, db: AsyncSession) -> None:
    """Удаляет истёкшие и отозванные refresh токены пользователя."""
    from sqlalchemy import delete, or_
    await db.execute(
        delete(RefreshToken).where(
            RefreshToken.user_id == user_id,
            or_(
                RefreshToken.expires_at < datetime.now(UTC),
                RefreshToken.revoked_at.is_not(None),
            ),
        )
    )


async def _init_user_defaults(user: User, db: AsyncSession) -> None:
    theme_id = await _get_default_theme_id(db)
    db.add(UserSettings(user_id=user.id, theme_id=theme_id))
    sub = Subscription(user_id=user.id, tier="free", status="active")
    db.add(sub)
    user.subscription = sub  # в памяти, без lazy-load запроса


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

    full_name = " ".join(filter(None, [data.first_name, data.last_name]))
    await notify(fmt_register(data.email, full_name))

    return _build_auth_response(user, access_token, refresh_token)


# ── Login ─────────────────────────────────────────────────────────

async def login(data: LoginRequest, db: AsyncSession) -> AuthResponse:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(User).where(User.email == data.email).options(selectinload(User.subscription))
    )
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    access_token, refresh_token = await _create_tokens_for_user(user, db, data.device_id)

    # Чистим истёкшие/отозванные токены этого пользователя (бесшумно)
    await _cleanup_old_tokens(user.id, db)

    tier = user.subscription.tier if user.subscription else "free"
    await notify(fmt_login(data.email, tier))

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

    allowed_auds = {settings.google_client_id, settings.google_ios_client_id}
    if google_data.get("aud") not in allowed_auds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token audience mismatch")

    if not google_data.get("email_verified"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email is not verified")

    google_user_id = google_data["sub"]
    email = google_data.get("email", "").lower().strip()
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No email in Google account")
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
        from sqlalchemy.orm import selectinload
        result = await db.execute(
            select(User).where(User.id == provider.user_id).options(selectinload(User.subscription))
        )
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


# ── Apple Sign In ─────────────────────────────────────────────────

async def apple_auth(data: AppleAuthRequest, db: AsyncSession) -> AuthResponse:
    from jose import JWTError, jwk, jwt as jose_jwt

    # Получаем публичные ключи Apple
    async with httpx.AsyncClient() as client:
        keys_resp = await client.get("https://appleid.apple.com/auth/keys", timeout=10)

    if keys_resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not fetch Apple public keys")

    apple_keys = keys_resp.json().get("keys", [])

    # Определяем какой ключ использовать по kid в заголовке токена
    try:
        header = jose_jwt.get_unverified_header(data.identity_token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Apple token")

    matching_key = next((k for k in apple_keys if k.get("kid") == header.get("kid")), None)
    if not matching_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Apple key not found")

    try:
        public_key = jwk.construct(matching_key)
        payload = jose_jwt.decode(
            data.identity_token,
            public_key.to_pem().decode(),
            algorithms=["RS256"],
            audience=settings.apple_bundle_id,
            issuer="https://appleid.apple.com",
        )
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Apple token")

    apple_user_id = payload.get("sub")
    if not apple_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Apple token payload")

    email = payload.get("email", "").lower().strip()

    # Ищем существующего пользователя по провайдеру
    result = await db.execute(
        select(AuthProvider).where(
            AuthProvider.provider == "apple",
            AuthProvider.provider_user_id == apple_user_id,
        )
    )
    provider = result.scalar_one_or_none()

    if provider:
        from sqlalchemy.orm import selectinload
        result = await db.execute(
            select(User).where(User.id == provider.user_id).options(selectinload(User.subscription))
        )
        user = result.scalar_one()
    else:
        user = None

        # Ищем по email если он есть в токене
        if email:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()

        if not user:
            # Apple присылает имя только при первом входе — берём из запроса
            first_name = (data.first_name or "").strip() or "User"
            last_name = (data.last_name or "").strip() or None

            if not email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email not provided by Apple and user not found",
                )

            user = User(email=email, first_name=first_name, last_name=last_name)
            db.add(user)
            await db.flush()
            await _init_user_defaults(user, db)

        db.add(AuthProvider(
            user_id=user.id,
            provider="apple",
            provider_user_id=apple_user_id,
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

    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(User).where(User.id == db_token.user_id).options(selectinload(User.subscription))
    )
    user = result.scalar_one()

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is disabled")

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
