import os
import aiosqlite
from backend.config import DB_PATH

CREATE_TABLES = [
    """CREATE TABLE IF NOT EXISTS users (
        id         INTEGER PRIMARY KEY,
        username   TEXT,
        first_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS categories (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        name    TEXT    NOT NULL,
        type    TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
        emoji   TEXT    NOT NULL DEFAULT '',
        user_id INTEGER REFERENCES users(id),
        UNIQUE(name, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS user_hidden_categories (
        user_id     INTEGER NOT NULL REFERENCES users(id),
        category_id INTEGER NOT NULL REFERENCES categories(id),
        PRIMARY KEY (user_id, category_id)
    )""",
    """CREATE TABLE IF NOT EXISTS transactions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id),
        category_id INTEGER NOT NULL REFERENCES categories(id),
        amount      REAL    NOT NULL CHECK (amount > 0),
        note        TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS category_limits (
        user_id     INTEGER NOT NULL REFERENCES users(id),
        category_id INTEGER NOT NULL REFERENCES categories(id),
        amount      REAL    NOT NULL CHECK (amount > 0),
        PRIMARY KEY (user_id, category_id)
    )""",
    """CREATE TABLE IF NOT EXISTS recurring_transactions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL REFERENCES users(id),
        category_id  INTEGER NOT NULL REFERENCES categories(id),
        amount       REAL    NOT NULL CHECK (amount > 0),
        day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
        created_at   TEXT DEFAULT (datetime('now'))
    )""",
]

SYSTEM_CATEGORIES = [
    ("Зарплата",       "income",  "💵"),
    ("Подарок",        "income",  "✨"),
    ("Инвестиции",     "income",  "🏦"),
    ("Другие доходы",  "income",  "💰"),
    ("Продукты",       "expense", "🥑"),
    ("Еда вне дома",   "expense", "🥡"),
    ("Транспорт",      "expense", "🛞"),
    ("Услуги",         "expense", "💧"),
    ("Подписки",       "expense", "🏷"),
    ("Церковь",        "expense", "🕊"),
    ("Одежда",         "expense", "🪡"),
    ("Для дома",       "expense", "🧺"),
    ("Уход",           "expense", "🧴"),
    ("Цветы",          "expense", "🪷"),
    ("Другие расходы", "expense", "💸"),
]


async def get_db() -> aiosqlite.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db() -> None:
    db = await get_db()
    try:
        for stmt in CREATE_TABLES:
            await db.execute(stmt)
        # Seed system categories only if none exist yet (NULL != NULL breaks INSERT OR IGNORE)
        async with db.execute("SELECT COUNT(*) FROM categories WHERE user_id IS NULL") as cur:
            count = (await cur.fetchone())[0]
        if count == 0:
            for name, type_, emoji in SYSTEM_CATEGORIES:
                await db.execute(
                    "INSERT INTO categories (name, type, emoji, user_id) VALUES (?, ?, ?, NULL)",
                    (name, type_, emoji),
                )
        await db.commit()
    finally:
        await db.close()


# ── Users ──────────────────────────────────────────────────────────────────

async def upsert_user(db, user_id: int, first_name: str, username: str | None) -> None:
    await db.execute(
        """INSERT INTO users (id, username, first_name) VALUES (?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               username   = excluded.username,
               first_name = excluded.first_name""",
        (user_id, username, first_name),
    )


# ── Categories ─────────────────────────────────────────────────────────────

async def get_visible_categories(db, user_id: int, type_: str | None = None) -> list[dict]:
    q = """SELECT c.id, c.name, c.type, c.emoji, c.user_id
           FROM categories c
           WHERE (c.user_id IS NULL OR c.user_id = ?)
             AND c.id NOT IN (
                 SELECT category_id FROM user_hidden_categories WHERE user_id = ?
             )"""
    params: list = [user_id, user_id]
    if type_:
        q += " AND c.type = ?"
        params.append(type_)
    q += " ORDER BY c.user_id IS NOT NULL, c.id"
    async with db.execute(q, params) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def get_hidden_categories(db, user_id: int) -> list[dict]:
    async with db.execute(
        """SELECT c.id, c.name, c.type, c.emoji
           FROM categories c
           JOIN user_hidden_categories uhc ON uhc.category_id = c.id
           WHERE uhc.user_id = ?""",
        (user_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def create_category(db, user_id: int, name: str, type_: str, emoji: str) -> int:
    cur = await db.execute(
        "INSERT INTO categories (name, type, emoji, user_id) VALUES (?, ?, ?, ?)",
        (name, type_, emoji, user_id),
    )
    return cur.lastrowid


async def delete_category(db, category_id: int, user_id: int) -> bool:
    cur = await db.execute(
        "DELETE FROM categories WHERE id = ? AND user_id = ?",
        (category_id, user_id),
    )
    return cur.rowcount > 0


async def hide_category(db, user_id: int, category_id: int) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO user_hidden_categories (user_id, category_id) VALUES (?, ?)",
        (user_id, category_id),
    )


async def unhide_category(db, user_id: int, category_id: int) -> None:
    await db.execute(
        "DELETE FROM user_hidden_categories WHERE user_id = ? AND category_id = ?",
        (user_id, category_id),
    )


# ── Transactions ───────────────────────────────────────────────────────────

async def get_transactions(
    db, user_id: int, limit: int = 20, offset: int = 0, year_month: str | None = None
) -> list[dict]:
    q = """SELECT t.id, t.amount, t.note, t.created_at,
                  c.name AS category_name, c.emoji AS category_emoji, c.type AS category_type
           FROM transactions t
           JOIN categories c ON c.id = t.category_id
           WHERE t.user_id = ?"""
    params: list = [user_id]
    if year_month:
        q += " AND strftime('%Y-%m', t.created_at) = ?"
        params.append(year_month)
    q += " ORDER BY t.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    async with db.execute(q, params) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def create_transaction(db, user_id: int, category_id: int, amount: float, note: str | None) -> int:
    cur = await db.execute(
        "INSERT INTO transactions (user_id, category_id, amount, note) VALUES (?, ?, ?, ?)",
        (user_id, category_id, amount, note),
    )
    return cur.lastrowid


async def delete_transaction(db, tx_id: int, user_id: int) -> bool:
    cur = await db.execute(
        "DELETE FROM transactions WHERE id = ? AND user_id = ?",
        (tx_id, user_id),
    )
    return cur.rowcount > 0


# ── Stats ──────────────────────────────────────────────────────────────────

def _period_filter(period: str, year_month: str | None = None) -> tuple[str, list]:
    """Returns (sql_fragment, extra_params) for WHERE clause."""
    if year_month:
        return "strftime('%Y-%m', t.created_at) = ?", [year_month]
    if period == "day":
        return "date(t.created_at) = date('now')", []
    if period == "week":
        return "t.created_at >= datetime('now', '-6 days')", []
    return "strftime('%Y-%m', t.created_at) = strftime('%Y-%m', 'now')", []


async def get_stats(db, user_id: int, period: str = "month", year_month: str | None = None) -> dict:
    pf, pf_params = _period_filter(period, year_month)
    async with db.execute(
        f"""SELECT
              COALESCE(SUM(CASE WHEN c.type='income'  THEN t.amount ELSE 0 END), 0) AS income,
              COALESCE(SUM(CASE WHEN c.type='expense' THEN t.amount ELSE 0 END), 0) AS expense
           FROM transactions t
           JOIN categories c ON c.id = t.category_id
           WHERE t.user_id = ? AND {pf}""",
        [user_id] + pf_params,
    ) as cur:
        row = await cur.fetchone()
    income, expense = row["income"], row["expense"]

    async with db.execute(
        f"""SELECT c.name, c.emoji, c.type, COALESCE(SUM(t.amount), 0) AS amount
           FROM transactions t
           JOIN categories c ON c.id = t.category_id
           WHERE t.user_id = ? AND {pf}
           GROUP BY c.id
           ORDER BY amount DESC""",
        [user_id] + pf_params,
    ) as cur:
        rows = await cur.fetchall()

    by_category = []
    for r in rows:
        total = income if r["type"] == "income" else expense
        percent = round(r["amount"] / total * 100, 1) if total > 0 else 0
        by_category.append({
            "name": r["name"],
            "emoji": r["emoji"],
            "type": r["type"],
            "amount": r["amount"],
            "percent": percent,
        })

    return {"balance": income - expense, "income": income, "expense": expense, "by_category": by_category}


# ── Limits ─────────────────────────────────────────────────────────────────

async def get_limits(db, user_id: int) -> list[dict]:
    async with db.execute(
        """SELECT cl.category_id, cl.amount AS limit_amount,
                  c.name, c.emoji, c.type,
                  COALESCE((
                      SELECT SUM(t.amount) FROM transactions t
                      WHERE t.category_id = cl.category_id AND t.user_id = cl.user_id
                        AND strftime('%Y-%m', t.created_at) = strftime('%Y-%m', 'now')
                  ), 0) AS spent
           FROM category_limits cl
           JOIN categories c ON c.id = cl.category_id
           WHERE cl.user_id = ?""",
        (user_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def set_limit(db, user_id: int, category_id: int, amount: float) -> None:
    await db.execute(
        """INSERT INTO category_limits (user_id, category_id, amount) VALUES (?, ?, ?)
           ON CONFLICT(user_id, category_id) DO UPDATE SET amount = excluded.amount""",
        (user_id, category_id, amount),
    )


async def delete_limit(db, user_id: int, category_id: int) -> bool:
    cur = await db.execute(
        "DELETE FROM category_limits WHERE user_id = ? AND category_id = ?",
        (user_id, category_id),
    )
    return cur.rowcount > 0


async def get_limit_status(db, user_id: int, category_id: int) -> dict | None:
    """Returns limit warning dict if >= 80%, else None."""
    async with db.execute(
        """SELECT cl.amount AS limit_amount,
                  COALESCE((
                      SELECT SUM(t.amount) FROM transactions t
                      WHERE t.category_id = ? AND t.user_id = ?
                        AND strftime('%Y-%m', t.created_at) = strftime('%Y-%m', 'now')
                  ), 0) AS spent
           FROM category_limits cl
           WHERE cl.user_id = ? AND cl.category_id = ?""",
        (category_id, user_id, user_id, category_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    spent, limit = row["spent"], row["limit_amount"]
    percent = spent / limit * 100 if limit > 0 else 0
    if percent >= 100:
        return {"level": "critical", "percent": round(percent, 1), "spent": spent, "limit": limit}
    if percent >= 80:
        return {"level": "warning", "percent": round(percent, 1), "spent": spent, "limit": limit}
    return None


# ── Recurring ──────────────────────────────────────────────────────────────

async def get_recurring(db, user_id: int) -> list[dict]:
    async with db.execute(
        """SELECT r.id, r.amount, r.day_of_month, r.created_at,
                  c.name AS category_name, c.emoji AS category_emoji, c.type AS category_type
           FROM recurring_transactions r
           JOIN categories c ON c.id = r.category_id
           WHERE r.user_id = ?
           ORDER BY r.day_of_month""",
        (user_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def create_recurring(db, user_id: int, category_id: int, amount: float, day_of_month: int) -> int:
    cur = await db.execute(
        "INSERT INTO recurring_transactions (user_id, category_id, amount, day_of_month) VALUES (?, ?, ?, ?)",
        (user_id, category_id, amount, day_of_month),
    )
    return cur.lastrowid


async def delete_recurring(db, rec_id: int, user_id: int) -> bool:
    cur = await db.execute(
        "DELETE FROM recurring_transactions WHERE id = ? AND user_id = ?",
        (rec_id, user_id),
    )
    return cur.rowcount > 0
