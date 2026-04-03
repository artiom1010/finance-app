import pytest
from httpx import AsyncClient

TX_URL = "/api/v1/transactions"
STATS_URL = "/api/v1/transactions/stats"


def make_tx(category_id: str, amount: str = "100.00", tx_type: str = "expense",
            date: str = "2024-01-15", note: str | None = None) -> dict:
    payload = {
        "category_id": category_id,
        "amount": amount,
        "type": tx_type,
        "date": date,
    }
    if note is not None:
        payload["note"] = note
    return payload


# ── Создание транзакций ───────────────────────────────────────────────────────

async def test_create_transaction_expense(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    resp = await client.post(TX_URL, json=make_tx(expense_category_id), headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["amount"] == "100.00"
    assert data["type"] == "expense"
    assert data["category"]["id"] == expense_category_id


async def test_create_transaction_income(
    client: AsyncClient, auth_headers: dict, income_category_id: str
):
    resp = await client.post(
        TX_URL,
        json=make_tx(income_category_id, amount="5000.00", tx_type="income"),
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["type"] == "income"


async def test_create_transaction_with_note(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    resp = await client.post(
        TX_URL,
        json=make_tx(expense_category_id, note="Lunch at cafe"),
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["note"] == "Lunch at cafe"


async def test_create_transaction_invalid_category(
    client: AsyncClient, auth_headers: dict
):
    import uuid
    resp = await client.post(
        TX_URL,
        json=make_tx(str(uuid.uuid4())),
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_create_transaction_negative_amount(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    resp = await client.post(
        TX_URL,
        json=make_tx(expense_category_id, amount="-50.00"),
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_create_transaction_requires_auth(
    client: AsyncClient, expense_category_id: str
):
    resp = await client.post(TX_URL, json=make_tx(expense_category_id))
    assert resp.status_code == 401


# ── Список транзакций ─────────────────────────────────────────────────────────

async def test_list_transactions_empty(client: AsyncClient, auth_headers: dict):
    resp = await client.get(TX_URL, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


async def test_list_transactions_pagination(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    # Создаём 3 транзакции
    for i in range(3):
        await client.post(TX_URL, json=make_tx(expense_category_id, amount=str(10 * (i + 1))), headers=auth_headers)

    resp = await client.get(f"{TX_URL}?limit=2&skip=0", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3


async def test_list_transactions_filter_by_type(
    client: AsyncClient, auth_headers: dict, expense_category_id: str, income_category_id: str
):
    await client.post(TX_URL, json=make_tx(expense_category_id), headers=auth_headers)
    await client.post(TX_URL, json=make_tx(income_category_id, tx_type="income"), headers=auth_headers)

    resp = await client.get(f"{TX_URL}?type=expense", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(t["type"] == "expense" for t in items)


async def test_list_transactions_filter_by_date(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    await client.post(TX_URL, json=make_tx(expense_category_id, date="2024-01-10"), headers=auth_headers)
    await client.post(TX_URL, json=make_tx(expense_category_id, date="2024-02-15"), headers=auth_headers)

    resp = await client.get(f"{TX_URL}?date_from=2024-02-01&date_to=2024-02-28", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["date"] == "2024-02-15"


async def test_list_transactions_filter_by_amount(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    await client.post(TX_URL, json=make_tx(expense_category_id, amount="50.00"), headers=auth_headers)
    await client.post(TX_URL, json=make_tx(expense_category_id, amount="200.00"), headers=auth_headers)

    resp = await client.get(f"{TX_URL}?amount_min=100", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert float(items[0]["amount"]) >= 100


async def test_list_transactions_search_by_note(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    await client.post(TX_URL, json=make_tx(expense_category_id, note="Coffee shop"), headers=auth_headers)
    await client.post(TX_URL, json=make_tx(expense_category_id, note="Taxi ride"), headers=auth_headers)

    resp = await client.get(f"{TX_URL}?search=coffee", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert "Coffee" in items[0]["note"]


# ── Получение одной транзакции ────────────────────────────────────────────────

async def test_get_transaction(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    create = await client.post(TX_URL, json=make_tx(expense_category_id), headers=auth_headers)
    tx_id = create.json()["id"]

    resp = await client.get(f"{TX_URL}/{tx_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == tx_id


async def test_get_transaction_not_found(client: AsyncClient, auth_headers: dict):
    import uuid
    resp = await client.get(f"{TX_URL}/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


async def test_get_other_users_transaction(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    # Создаём вторым пользователем
    reg2 = await client.post("/api/v1/auth/register", json={
        "email": "other@example.com", "password": "OtherPass123", "first_name": "Other"
    })
    headers2 = {"Authorization": f"Bearer {reg2.json()['access_token']}"}
    create = await client.post(TX_URL, json=make_tx(expense_category_id), headers=headers2)
    tx_id = create.json()["id"]

    # Первый пользователь не должен видеть транзакцию второго
    resp = await client.get(f"{TX_URL}/{tx_id}", headers=auth_headers)
    assert resp.status_code == 404


# ── Обновление транзакции ─────────────────────────────────────────────────────

async def test_update_transaction_amount(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    create = await client.post(TX_URL, json=make_tx(expense_category_id), headers=auth_headers)
    tx_id = create.json()["id"]

    resp = await client.patch(f"{TX_URL}/{tx_id}", json={"amount": "250.50"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["amount"] == "250.50"


async def test_update_transaction_clear_note(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    create = await client.post(TX_URL, json=make_tx(expense_category_id, note="Old note"), headers=auth_headers)
    tx_id = create.json()["id"]

    # note=null должен очистить заметку
    resp = await client.patch(f"{TX_URL}/{tx_id}", json={"note": None}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["note"] is None


# ── Удаление и восстановление ─────────────────────────────────────────────────

async def test_delete_transaction(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    create = await client.post(TX_URL, json=make_tx(expense_category_id), headers=auth_headers)
    tx_id = create.json()["id"]

    resp = await client.delete(f"{TX_URL}/{tx_id}", headers=auth_headers)
    assert resp.status_code == 204

    # Удалённая транзакция не видна в списке
    resp = await client.get(f"{TX_URL}/{tx_id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_restore_transaction(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    create = await client.post(TX_URL, json=make_tx(expense_category_id), headers=auth_headers)
    tx_id = create.json()["id"]

    await client.delete(f"{TX_URL}/{tx_id}", headers=auth_headers)

    resp = await client.post(f"{TX_URL}/{tx_id}/restore", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == tx_id

    # Теперь снова видна
    resp = await client.get(f"{TX_URL}/{tx_id}", headers=auth_headers)
    assert resp.status_code == 200


# ── Статистика ────────────────────────────────────────────────────────────────

async def test_stats_empty(client: AsyncClient, auth_headers: dict):
    resp = await client.get(STATS_URL, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["income_total"] == "0"
    assert data["expense_total"] == "0"
    assert data["balance"] == "0"


async def test_stats_with_transactions(
    client: AsyncClient, auth_headers: dict,
    expense_category_id: str, income_category_id: str
):
    await client.post(TX_URL, json=make_tx(income_category_id, amount="3000.00", tx_type="income"), headers=auth_headers)
    await client.post(TX_URL, json=make_tx(expense_category_id, amount="500.00"), headers=auth_headers)
    await client.post(TX_URL, json=make_tx(expense_category_id, amount="200.00"), headers=auth_headers)

    resp = await client.get(STATS_URL, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert float(data["income_total"]) == 3000.00
    assert float(data["expense_total"]) == 700.00
    assert float(data["balance"]) == 2300.00
    assert len(data["expense_by_category"]) == 1
    assert len(data["income_by_category"]) == 1


async def test_stats_date_filter(
    client: AsyncClient, auth_headers: dict, expense_category_id: str
):
    await client.post(TX_URL, json=make_tx(expense_category_id, amount="100.00", date="2024-01-10"), headers=auth_headers)
    await client.post(TX_URL, json=make_tx(expense_category_id, amount="200.00", date="2024-03-10"), headers=auth_headers)

    resp = await client.get(f"{STATS_URL}?date_from=2024-01-01&date_to=2024-01-31", headers=auth_headers)
    assert resp.status_code == 200
    assert float(resp.json()["expense_total"]) == 100.00
