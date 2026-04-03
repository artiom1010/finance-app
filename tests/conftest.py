"""
Test infrastructure.

Требования: Postgres.app или docker-compose up postgres (порт 5432 на localhost).
Каждый тест получает собственный async engine — нет проблем с event loop.
Создание/удаление тестовой БД происходит синхронно через subprocess (psql).
"""
import asyncio
import subprocess
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app

# ── Константы ──────────────────────────────────────────────────────────────────

TEST_DB_URL = (
    f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
    f"@localhost:{settings.postgres_port}/financeai_test"
)

# Путь к psql (Postgres.app или системный)
_PSQL_CANDIDATES = [
    "/Applications/Postgres.app/Contents/Versions/latest/bin/psql",
    "/usr/local/bin/psql",
    "/usr/bin/psql",
]
PSQL = next((p for p in _PSQL_CANDIDATES if __import__("os").path.exists(p)), "psql")


# ── Helpers: синхронное создание/удаление БД ──────────────────────────────────

def _psql(sql: str) -> None:
    """Запускает SQL в postgres-базе через psql (суперпользователь = текущий OS user)."""
    import getpass
    subprocess.run(
        [PSQL, "-U", getpass.getuser(), "-h", "localhost",
         "-p", str(settings.postgres_port), "-d", "postgres", "-c", sql],
        check=True, capture_output=True,
    )


def _create_test_db() -> None:
    _psql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'financeai_test'")
    _psql("DROP DATABASE IF EXISTS financeai_test")
    _psql(f"CREATE DATABASE financeai_test OWNER {settings.postgres_user}")


def _drop_test_db() -> None:
    _psql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'financeai_test'")
    _psql("DROP DATABASE IF EXISTS financeai_test")


async def _setup_schema_and_seed() -> None:
    """Создаём таблицы и сидируем системные данные. Запускается через asyncio.run()."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO currencies (code, name, symbol) VALUES
                ('USD', 'US Dollar', '$'), ('EUR', 'Euro', '€')
                ON CONFLICT DO NOTHING
            """))
            await conn.execute(text("""
                INSERT INTO themes (id, name) VALUES
                (:light_id, 'light'), (:dark_id, 'dark')
                ON CONFLICT DO NOTHING
            """), {"light_id": str(uuid.uuid4()), "dark_id": str(uuid.uuid4())})
            await conn.execute(text("""
                INSERT INTO categories (id, name, icon, color, type, is_active, sort_order) VALUES
                (:id1, 'Food & Drinks', '🍔', '#F59E0B', 'expense', true, 1),
                (:id2, 'Salary',        '💼', '#22C55E', 'income',  true, 1)
                ON CONFLICT DO NOTHING
            """), {"id1": str(uuid.uuid4()), "id2": str(uuid.uuid4())})
    finally:
        await engine.dispose()


async def _cleanup_user_data() -> None:
    """Удаляет все пользовательские данные. Запускается через asyncio.run()."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    try:
        async with engine.begin() as conn:
            for table in [
                "ai_messages", "ai_usage",
                "transactions",
                "user_settings",
                "subscriptions",
                "auth_providers",
                "refresh_tokens",
                "users",
            ]:
                await conn.execute(text(f"DELETE FROM {table}"))
            # Пользовательские категории (user_id NOT NULL)
            await conn.execute(text("DELETE FROM categories WHERE user_id IS NOT NULL"))
    finally:
        await engine.dispose()


# ── Session-scoped фикстуры ───────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Создаём тестовую БД, таблицы и системные данные — один раз на всю сессию."""
    _create_test_db()
    asyncio.run(_setup_schema_and_seed())
    yield
    _drop_test_db()


# ── Function-scoped фикстуры ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_user_data():
    """Очищаем пользовательские данные после каждого теста."""
    yield
    asyncio.run(_cleanup_user_data())


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент с тестовой БД. Каждый тест получает свой engine (нет loop-конфликтов)."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


# ── Вспомогательные фикстуры ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def registered_user(client: AsyncClient) -> dict[str, Any]:
    resp = await client.post("/api/v1/auth/register", json={
        "email": "test@example.com",
        "password": "TestPass123",
        "first_name": "Test",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest_asyncio.fixture
async def auth_headers(registered_user: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered_user['access_token']}"}


@pytest_asyncio.fixture
async def expense_category_id(client: AsyncClient, auth_headers: dict) -> str:
    resp = await client.get("/api/v1/categories", headers=auth_headers)
    assert resp.status_code == 200
    return next(c["id"] for c in resp.json() if c["type"] == "expense")


@pytest_asyncio.fixture
async def income_category_id(client: AsyncClient, auth_headers: dict) -> str:
    resp = await client.get("/api/v1/categories", headers=auth_headers)
    assert resp.status_code == 200
    return next(c["id"] for c in resp.json() if c["type"] == "income")
