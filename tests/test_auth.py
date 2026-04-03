import pytest
from httpx import AsyncClient


REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"

VALID_USER = {
    "email": "user@example.com",
    "password": "StrongPass123",
    "first_name": "Ivan",
    "last_name": "Petrov",
}


# ── Регистрация ───────────────────────────────────────────────────────────────

async def test_register_success(client: AsyncClient):
    resp = await client.post(REGISTER_URL, json=VALID_USER)
    assert resp.status_code == 201
    data = resp.json()
    assert data["user"]["email"] == VALID_USER["email"]
    assert data["user"]["first_name"] == VALID_USER["first_name"]
    assert data["user"]["tier"] == "free"
    assert "access_token" in data
    assert "refresh_token" in data


async def test_register_normalizes_email(client: AsyncClient):
    payload = {**VALID_USER, "email": "  USER@EXAMPLE.COM  "}
    resp = await client.post(REGISTER_URL, json=payload)
    assert resp.status_code == 201
    assert resp.json()["user"]["email"] == "user@example.com"


async def test_register_duplicate_email(client: AsyncClient):
    await client.post(REGISTER_URL, json=VALID_USER)
    resp = await client.post(REGISTER_URL, json=VALID_USER)
    assert resp.status_code == 409


async def test_register_password_too_short(client: AsyncClient):
    resp = await client.post(REGISTER_URL, json={**VALID_USER, "password": "123"})
    assert resp.status_code == 422


async def test_register_password_too_long(client: AsyncClient):
    resp = await client.post(REGISTER_URL, json={**VALID_USER, "password": "x" * 129})
    assert resp.status_code == 422


async def test_register_empty_first_name(client: AsyncClient):
    resp = await client.post(REGISTER_URL, json={**VALID_USER, "first_name": "   "})
    assert resp.status_code == 422


async def test_register_invalid_email(client: AsyncClient):
    resp = await client.post(REGISTER_URL, json={**VALID_USER, "email": "not-an-email"})
    assert resp.status_code == 422


# ── Логин ─────────────────────────────────────────────────────────────────────

async def test_login_success(client: AsyncClient):
    await client.post(REGISTER_URL, json=VALID_USER)
    resp = await client.post(LOGIN_URL, json={
        "email": VALID_USER["email"],
        "password": VALID_USER["password"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


async def test_login_wrong_password(client: AsyncClient):
    await client.post(REGISTER_URL, json=VALID_USER)
    resp = await client.post(LOGIN_URL, json={
        "email": VALID_USER["email"],
        "password": "WrongPassword",
    })
    assert resp.status_code == 401


async def test_login_unknown_email(client: AsyncClient):
    resp = await client.post(LOGIN_URL, json={
        "email": "nobody@example.com",
        "password": "SomePass123",
    })
    assert resp.status_code == 401


async def test_login_normalizes_email(client: AsyncClient):
    await client.post(REGISTER_URL, json=VALID_USER)
    resp = await client.post(LOGIN_URL, json={
        "email": "  USER@EXAMPLE.COM  ",
        "password": VALID_USER["password"],
    })
    assert resp.status_code == 200


# ── Refresh ───────────────────────────────────────────────────────────────────

async def test_refresh_tokens(client: AsyncClient):
    reg = await client.post(REGISTER_URL, json=VALID_USER)
    refresh_token = reg.json()["refresh_token"]

    resp = await client.post(REFRESH_URL, json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    # Новый refresh токен должен отличаться (ротация)
    assert data["refresh_token"] != refresh_token


async def test_refresh_old_token_revoked(client: AsyncClient):
    reg = await client.post(REGISTER_URL, json=VALID_USER)
    old_refresh = reg.json()["refresh_token"]

    # Используем токен первый раз
    await client.post(REFRESH_URL, json={"refresh_token": old_refresh})

    # Повторное использование старого токена должно вернуть ошибку
    resp = await client.post(REFRESH_URL, json={"refresh_token": old_refresh})
    assert resp.status_code == 401


async def test_refresh_invalid_token(client: AsyncClient):
    resp = await client.post(REFRESH_URL, json={"refresh_token": "invalid.token.here"})
    assert resp.status_code == 401


# ── Logout ────────────────────────────────────────────────────────────────────

async def test_logout_success(client: AsyncClient):
    reg = await client.post(REGISTER_URL, json=VALID_USER)
    refresh_token = reg.json()["refresh_token"]

    resp = await client.post(LOGOUT_URL, json={"refresh_token": refresh_token})
    assert resp.status_code == 204

    # После logout refresh токен должен быть недействителен
    resp = await client.post(REFRESH_URL, json={"refresh_token": refresh_token})
    assert resp.status_code == 401


# ── Защищённые эндпоинты без токена ──────────────────────────────────────────

async def test_protected_endpoint_without_token(client: AsyncClient):
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


async def test_protected_endpoint_with_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer invalid.token"}
    )
    assert resp.status_code == 401
