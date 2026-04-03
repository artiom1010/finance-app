from typing import Any

import pytest
from httpx import AsyncClient


ME_URL = "/api/v1/users/me"
SETTINGS_URL = "/api/v1/users/me/settings"
CHANGE_PW_URL = "/api/v1/users/me/change-password"
PROVIDERS_URL = "/api/v1/users/me/providers"
SESSIONS_URL = "/api/v1/users/me/sessions"
CURRENCIES_URL = "/api/v1/users/currencies"
THEMES_URL = "/api/v1/users/themes"


# ── Профиль ───────────────────────────────────────────────────────────────────

async def test_get_me(client: AsyncClient, registered_user: dict, auth_headers: dict):
    resp = await client.get(ME_URL, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert data["first_name"] == "Test"
    assert data["tier"] == "free"


async def test_update_me_first_name(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(ME_URL, json={"first_name": "Updated"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Updated"


async def test_update_me_last_name(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(ME_URL, json={"last_name": "Smith"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["last_name"] == "Smith"


async def test_update_me_empty_first_name_rejected(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(ME_URL, json={"first_name": ""}, headers=auth_headers)
    assert resp.status_code == 422


# ── Настройки ─────────────────────────────────────────────────────────────────

async def test_get_settings(client: AsyncClient, auth_headers: dict):
    resp = await client.get(SETTINGS_URL, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["currency_code"] == "USD"
    assert data["font_size"] == "medium"
    assert data["notifications_enabled"] is True


async def test_update_settings_currency(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(SETTINGS_URL, json={"currency_code": "EUR"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["currency_code"] == "EUR"


async def test_update_settings_invalid_currency(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(SETTINGS_URL, json={"currency_code": "XYZ"}, headers=auth_headers)
    assert resp.status_code == 404


async def test_update_settings_font_size(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(SETTINGS_URL, json={"font_size": "large"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["font_size"] == "large"


async def test_update_settings_invalid_font_size(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(SETTINGS_URL, json={"font_size": "huge"}, headers=auth_headers)
    assert resp.status_code == 422


async def test_update_settings_notifications(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(SETTINGS_URL, json={"notifications_enabled": False}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["notifications_enabled"] is False


async def test_update_settings_week_starts_on(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(SETTINGS_URL, json={"week_starts_on": 0}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["week_starts_on"] == 0


async def test_update_settings_invalid_week_starts_on(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(SETTINGS_URL, json={"week_starts_on": 7}, headers=auth_headers)
    assert resp.status_code == 422


# ── Смена пароля ──────────────────────────────────────────────────────────────

async def test_change_password_success(client: AsyncClient, auth_headers: dict):
    resp = await client.post(CHANGE_PW_URL, json={
        "current_password": "TestPass123",
        "new_password": "NewSecurePass456",
    }, headers=auth_headers)
    assert resp.status_code == 204

    # Проверяем что новый пароль работает
    login = await client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "NewSecurePass456",
    })
    assert login.status_code == 200


async def test_change_password_wrong_current(client: AsyncClient, auth_headers: dict):
    resp = await client.post(CHANGE_PW_URL, json={
        "current_password": "WrongPassword",
        "new_password": "NewSecurePass456",
    }, headers=auth_headers)
    assert resp.status_code == 400


async def test_change_password_too_short(client: AsyncClient, auth_headers: dict):
    resp = await client.post(CHANGE_PW_URL, json={
        "current_password": "TestPass123",
        "new_password": "short",
    }, headers=auth_headers)
    assert resp.status_code == 422


# ── Подписка ──────────────────────────────────────────────────────────────────

async def test_get_subscription(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/users/me/subscription", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "free"
    assert data["status"] == "active"


# ── OAuth провайдеры ──────────────────────────────────────────────────────────

async def test_list_providers_empty(client: AsyncClient, auth_headers: dict):
    resp = await client.get(PROVIDERS_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


# ── Сессии ────────────────────────────────────────────────────────────────────

async def test_list_sessions(client: AsyncClient, registered_user: dict, auth_headers: dict):
    resp = await client.get(SESSIONS_URL, headers=auth_headers)
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) >= 1  # хотя бы текущая сессия


async def test_revoke_session(client: AsyncClient, registered_user: dict, auth_headers: dict):
    sessions = (await client.get(SESSIONS_URL, headers=auth_headers)).json()
    session_id = sessions[0]["id"]

    resp = await client.delete(f"{SESSIONS_URL}/{session_id}", headers=auth_headers)
    assert resp.status_code == 204

    # Токен из отозванной сессии больше не работает
    refresh_token = registered_user["refresh_token"]
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401


async def test_revoke_nonexistent_session(client: AsyncClient, auth_headers: dict):
    import uuid
    resp = await client.delete(
        f"{SESSIONS_URL}/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── Удаление аккаунта ─────────────────────────────────────────────────────────

async def test_delete_account(client: AsyncClient, registered_user: dict, auth_headers: dict):
    resp = await client.delete(ME_URL, headers=auth_headers)
    assert resp.status_code == 204

    # После удаления токены не работают
    resp = await client.get(ME_URL, headers=auth_headers)
    assert resp.status_code == 401


# ── Справочники ───────────────────────────────────────────────────────────────

async def test_get_currencies(client: AsyncClient):
    resp = await client.get(CURRENCIES_URL)
    assert resp.status_code == 200
    currencies = resp.json()
    assert len(currencies) >= 2
    codes = [c["code"] for c in currencies]
    assert "USD" in codes
    assert "EUR" in codes


async def test_get_themes(client: AsyncClient):
    resp = await client.get(THEMES_URL)
    assert resp.status_code == 200
    themes = resp.json()
    assert len(themes) >= 1
    names = [t["name"] for t in themes]
    assert "light" in names
