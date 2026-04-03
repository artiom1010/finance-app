from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

TEMPLATES_URL = "/api/v1/ai/templates"
CHAT_URL = "/api/v1/ai/chat"
ASK_URL = "/api/v1/ai/ask"
CLEAR_URL = "/api/v1/ai/chat"
MESSAGES_URL = "/api/v1/ai/messages"

# Мок ответа Anthropic — не делаем реальных запросов в тестах
MOCK_RESPONSE = ("Вот мой анализ ваших расходов.", 150)


def mock_anthropic():
    """Патч для _call_anthropic чтобы не ходить в API Anthropic."""
    return patch(
        "app.services.ai._call_anthropic",
        new_callable=AsyncMock,
        return_value=MOCK_RESPONSE,
    )


# ── Шаблоны ───────────────────────────────────────────────────────────────────

async def test_get_templates(client: AsyncClient, auth_headers: dict):
    resp = await client.get(TEMPLATES_URL, headers=auth_headers)
    assert resp.status_code == 200
    templates = resp.json()
    # Шаблоны созданы через сид в conftest, но в тесте их может не быть
    # Проверяем только структуру
    assert isinstance(templates, list)
    for t in templates:
        assert "id" in t
        assert "label" in t
        assert "icon" in t
        assert "is_active" in t


async def test_get_templates_requires_auth(client: AsyncClient):
    resp = await client.get(TEMPLATES_URL)
    assert resp.status_code == 401


# ── История чата ──────────────────────────────────────────────────────────────

async def test_get_chat_empty(client: AsyncClient, auth_headers: dict):
    resp = await client.get(CHAT_URL, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["messages"] == []
    assert data["requests_today"] == 0
    assert data["daily_limit"] == 5  # free tier


async def test_get_chat_requires_auth(client: AsyncClient):
    resp = await client.get(CHAT_URL)
    assert resp.status_code == 401


# ── Вопрос ИИ ─────────────────────────────────────────────────────────────────

async def test_ask_question(client: AsyncClient, auth_headers: dict):
    with mock_anthropic():
        resp = await client.post(ASK_URL, json={"message": "Как снизить расходы?"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "assistant"
    assert data["content"] == MOCK_RESPONSE[0]
    assert data["tokens_used"] == MOCK_RESPONSE[1]


async def test_ask_increments_counter(client: AsyncClient, auth_headers: dict):
    with mock_anthropic():
        await client.post(ASK_URL, json={"message": "Вопрос 1"}, headers=auth_headers)
        await client.post(ASK_URL, json={"message": "Вопрос 2"}, headers=auth_headers)

    chat = await client.get(CHAT_URL, headers=auth_headers)
    assert chat.json()["requests_today"] == 2


async def test_ask_empty_message_rejected(client: AsyncClient, auth_headers: dict):
    resp = await client.post(ASK_URL, json={"message": ""}, headers=auth_headers)
    assert resp.status_code == 422


async def test_ask_too_long_message_rejected(client: AsyncClient, auth_headers: dict):
    resp = await client.post(ASK_URL, json={"message": "x" * 2001}, headers=auth_headers)
    assert resp.status_code == 422


async def test_ask_messages_appear_in_chat(client: AsyncClient, auth_headers: dict):
    with mock_anthropic():
        await client.post(ASK_URL, json={"message": "Тест"}, headers=auth_headers)

    chat = (await client.get(CHAT_URL, headers=auth_headers)).json()
    assert len(chat["messages"]) == 2  # user + assistant
    roles = [m["role"] for m in chat["messages"]]
    assert "user" in roles
    assert "assistant" in roles


# ── Дневной лимит (free tier = 5 запросов) ────────────────────────────────────

async def test_daily_limit_enforced(client: AsyncClient, auth_headers: dict):
    with mock_anthropic():
        for i in range(5):
            resp = await client.post(ASK_URL, json={"message": f"Вопрос {i}"}, headers=auth_headers)
            assert resp.status_code == 200

        # 6-й запрос должен быть отклонён
        resp = await client.post(ASK_URL, json={"message": "Вопрос 6"}, headers=auth_headers)
        assert resp.status_code == 403
        assert "limit" in resp.json()["detail"].lower()


# ── Очистка чата ──────────────────────────────────────────────────────────────

async def test_clear_chat(client: AsyncClient, auth_headers: dict):
    with mock_anthropic():
        await client.post(ASK_URL, json={"message": "Сообщение"}, headers=auth_headers)

    resp = await client.delete(CLEAR_URL, headers=auth_headers)
    assert resp.status_code == 204

    # После очистки история пуста
    chat = (await client.get(CHAT_URL, headers=auth_headers)).json()
    assert chat["messages"] == []


async def test_clear_chat_does_not_reset_counter(client: AsyncClient, auth_headers: dict):
    with mock_anthropic():
        await client.post(ASK_URL, json={"message": "Сообщение"}, headers=auth_headers)

    await client.delete(CLEAR_URL, headers=auth_headers)

    chat = (await client.get(CHAT_URL, headers=auth_headers)).json()
    # Счётчик за день сохраняется даже после очистки истории
    assert chat["requests_today"] == 1


# ── Удаление отдельного сообщения ─────────────────────────────────────────────

async def test_delete_single_message(client: AsyncClient, auth_headers: dict):
    with mock_anthropic():
        await client.post(ASK_URL, json={"message": "Сообщение для удаления"}, headers=auth_headers)

    chat = (await client.get(CHAT_URL, headers=auth_headers)).json()
    user_msg = next(m for m in chat["messages"] if m["role"] == "user")
    msg_id = user_msg["id"]

    resp = await client.delete(f"{MESSAGES_URL}/{msg_id}", headers=auth_headers)
    assert resp.status_code == 204

    # Сообщение больше не видно в чате
    chat_after = (await client.get(CHAT_URL, headers=auth_headers)).json()
    ids = [m["id"] for m in chat_after["messages"]]
    assert msg_id not in ids


async def test_delete_nonexistent_message(client: AsyncClient, auth_headers: dict):
    import uuid
    resp = await client.delete(f"{MESSAGES_URL}/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
