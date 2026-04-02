import uuid

from pydantic import BaseModel, EmailStr, field_validator


# ── Регистрация ───────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("first_name")
    @classmethod
    def first_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("first_name cannot be empty")
        return v.strip()


# ── Логин ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    device_id: str | None = None    # для привязки refresh токена к устройству


# ── Google OAuth ──────────────────────────────────────────────────

class GoogleAuthRequest(BaseModel):
    id_token: str                   # токен от Google Sign-In SDK
    device_id: str | None = None


# ── Refresh ───────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str


# ── Responses ─────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str | None
    tier: str                       # 'free' | 'pro' — из subscription

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
