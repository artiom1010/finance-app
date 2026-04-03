import pytest
from httpx import AsyncClient

CAT_URL = "/api/v1/categories"

NEW_CATEGORY = {
    "name": "My Category",
    "icon": "🎯",
    "color": "#FF5733",
    "type": "expense",
}


# ── Список категорий ──────────────────────────────────────────────────────────

async def test_list_categories_includes_system(client: AsyncClient, auth_headers: dict):
    resp = await client.get(CAT_URL, headers=auth_headers)
    assert resp.status_code == 200
    categories = resp.json()
    # Должны быть системные категории (user_id = None)
    system = [c for c in categories if c["user_id"] is None]
    assert len(system) >= 2


async def test_list_categories_requires_auth(client: AsyncClient):
    resp = await client.get(CAT_URL)
    assert resp.status_code == 401


# ── Создание категории ────────────────────────────────────────────────────────

async def test_create_category(client: AsyncClient, auth_headers: dict):
    resp = await client.post(CAT_URL, json=NEW_CATEGORY, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Category"
    assert data["icon"] == "🎯"
    assert data["color"] == "#FF5733"
    assert data["type"] == "expense"
    assert data["is_active"] is True


async def test_create_category_invalid_type(client: AsyncClient, auth_headers: dict):
    resp = await client.post(CAT_URL, json={**NEW_CATEGORY, "type": "invalid"}, headers=auth_headers)
    assert resp.status_code == 422


async def test_create_category_empty_name(client: AsyncClient, auth_headers: dict):
    resp = await client.post(CAT_URL, json={**NEW_CATEGORY, "name": ""}, headers=auth_headers)
    assert resp.status_code == 422


async def test_create_category_both_type(client: AsyncClient, auth_headers: dict):
    resp = await client.post(CAT_URL, json={**NEW_CATEGORY, "type": "both"}, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["type"] == "both"


# ── Обновление категории ──────────────────────────────────────────────────────

async def test_update_category_name(client: AsyncClient, auth_headers: dict):
    create = await client.post(CAT_URL, json=NEW_CATEGORY, headers=auth_headers)
    cat_id = create.json()["id"]

    resp = await client.patch(f"{CAT_URL}/{cat_id}", json={"name": "Updated Name"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


async def test_update_category_icon(client: AsyncClient, auth_headers: dict):
    create = await client.post(CAT_URL, json=NEW_CATEGORY, headers=auth_headers)
    cat_id = create.json()["id"]

    resp = await client.patch(f"{CAT_URL}/{cat_id}", json={"icon": "🚀"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["icon"] == "🚀"


async def test_update_category_sort_order(client: AsyncClient, auth_headers: dict):
    create = await client.post(CAT_URL, json=NEW_CATEGORY, headers=auth_headers)
    cat_id = create.json()["id"]

    resp = await client.patch(f"{CAT_URL}/{cat_id}", json={"sort_order": 5}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["sort_order"] == 5


async def test_update_system_category_forbidden(client: AsyncClient, auth_headers: dict):
    # Системные категории нельзя редактировать (user_id = None → не найдена для юзера)
    cats = (await client.get(CAT_URL, headers=auth_headers)).json()
    system_id = next(c["id"] for c in cats if c["user_id"] is None)

    resp = await client.patch(f"{CAT_URL}/{system_id}", json={"name": "Hacked"}, headers=auth_headers)
    assert resp.status_code == 404


async def test_update_nonexistent_category(client: AsyncClient, auth_headers: dict):
    import uuid
    resp = await client.patch(f"{CAT_URL}/{uuid.uuid4()}", json={"name": "X"}, headers=auth_headers)
    assert resp.status_code == 404


# ── Удаление и восстановление ─────────────────────────────────────────────────

async def test_delete_category(client: AsyncClient, auth_headers: dict):
    create = await client.post(CAT_URL, json=NEW_CATEGORY, headers=auth_headers)
    cat_id = create.json()["id"]

    resp = await client.delete(f"{CAT_URL}/{cat_id}", headers=auth_headers)
    assert resp.status_code == 204

    # Удалённая категория не видна в списке
    cats = (await client.get(CAT_URL, headers=auth_headers)).json()
    ids = [c["id"] for c in cats]
    assert cat_id not in ids


async def test_restore_category(client: AsyncClient, auth_headers: dict):
    create = await client.post(CAT_URL, json=NEW_CATEGORY, headers=auth_headers)
    cat_id = create.json()["id"]

    await client.delete(f"{CAT_URL}/{cat_id}", headers=auth_headers)

    resp = await client.post(f"{CAT_URL}/{cat_id}/restore", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    # Снова видна в списке
    cats = (await client.get(CAT_URL, headers=auth_headers)).json()
    ids = [c["id"] for c in cats]
    assert cat_id in ids


async def test_delete_system_category_forbidden(client: AsyncClient, auth_headers: dict):
    cats = (await client.get(CAT_URL, headers=auth_headers)).json()
    system_id = next(c["id"] for c in cats if c["user_id"] is None)

    resp = await client.delete(f"{CAT_URL}/{system_id}", headers=auth_headers)
    assert resp.status_code == 404


# ── Изоляция пользователей ────────────────────────────────────────────────────

async def test_category_not_visible_to_other_user(client: AsyncClient, auth_headers: dict):
    create = await client.post(CAT_URL, json=NEW_CATEGORY, headers=auth_headers)
    cat_id = create.json()["id"]

    reg2 = await client.post("/api/v1/auth/register", json={
        "email": "other@example.com", "password": "OtherPass123", "first_name": "Other"
    })
    headers2 = {"Authorization": f"Bearer {reg2.json()['access_token']}"}

    cats2 = (await client.get(CAT_URL, headers=headers2)).json()
    ids2 = [c["id"] for c in cats2]
    assert cat_id not in ids2
