from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.auth import (
    AuthResponse,
    GoogleAuthRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth")


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Регистрация через email + пароль."""
    return await auth_service.register(data, db)


@router.post("/login", response_model=AuthResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Логин через email + пароль."""
    return await auth_service.login(data, db)


@router.post("/google", response_model=AuthResponse)
async def google_auth(data: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    """Авторизация через Google OAuth (id_token от Flutter Google Sign-In)."""
    return await auth_service.google_auth(data, db)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Обновление access токена. Старый refresh токен отзывается, выдаётся новый."""
    return await auth_service.refresh_tokens(data.refresh_token, db)


@router.post("/logout", status_code=204)
async def logout(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Выход: отзывает refresh токен. Access токен истечёт сам (30 мин)."""
    await auth_service.logout(data.refresh_token, db)
