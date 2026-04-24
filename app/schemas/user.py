import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str | None
    tier: str

    model_config = {"from_attributes": True}


class UserProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


class UserSettingsResponse(BaseModel):
    currency_code: str
    theme_id: uuid.UUID
    font_size: str
    language: str
    week_starts_on: int
    notifications_enabled: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserSettingsUpdate(BaseModel):
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    theme_id: uuid.UUID | None = None
    font_size: str | None = Field(default=None, pattern="^(small|medium|large)$")
    language: str | None = Field(default=None, min_length=2, max_length=10)
    week_starts_on: int | None = Field(default=None, ge=0, le=6)
    notifications_enabled: bool | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class CurrencyResponse(BaseModel):
    code: str
    name: str
    symbol: str

    model_config = {"from_attributes": True}


class ThemeResponse(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class SubscriptionResponse(BaseModel):
    tier: str
    status: str
    store: str | None
    revenuecat_customer_id: str | None
    expires_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuthProviderResponse(BaseModel):
    provider: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionResponse(BaseModel):
    id: uuid.UUID
    device_id: str | None
    created_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}


class EmailChangeRequest(BaseModel):
    new_email: EmailStr
    current_password: str
