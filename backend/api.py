import os
from typing import AsyncGenerator

import aiosqlite
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import backend.database as db
from backend.auth import verify_telegram_data
from backend.config import CORS_ORIGINS, DEBUG

app = FastAPI(title="Finance Mini App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await db.init_db()


async def get_conn() -> AsyncGenerator[aiosqlite.Connection, None]:
    conn = await db.get_db()
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()


# ── Auth ───────────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    initData: str


@app.post("/api/auth")
async def auth(body: AuthRequest, conn=Depends(get_conn)):
    if DEBUG and body.initData.startswith("debug:"):
        # Format for local dev: "debug:{user_id}:{first_name}:{username}"
        parts = body.initData.split(":")
        user_id = int(parts[1])
        first_name = parts[2] if len(parts) > 2 else "Dev"
        username = parts[3] if len(parts) > 3 else None
    else:
        data = verify_telegram_data(body.initData)
        if not data:
            raise HTTPException(status_code=401, detail="Invalid initData")
        user_id = data["user_id"]
        first_name = data["first_name"]
        username = data.get("username")

    await db.upsert_user(conn, user_id, first_name, username)
    return {"user_id": user_id, "first_name": first_name, "username": username}


# ── Transactions ───────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    user_id: int
    category_id: int
    amount: float
    note: str | None = None


@app.get("/api/transactions")
async def list_transactions(
    user_id: int,
    limit: int = Query(20, le=100),
    offset: int = 0,
    year_month: str | None = None,
    conn=Depends(get_conn),
):
    import re
    if year_month and not re.match(r"^\d{4}-\d{2}$", year_month):
        raise HTTPException(400, "year_month must be YYYY-MM")
    return await db.get_transactions(conn, user_id, limit, offset, year_month)


@app.post("/api/transactions", status_code=201)
async def create_transaction(body: TransactionCreate, conn=Depends(get_conn)):
    if body.amount <= 0:
        raise HTTPException(400, "amount must be > 0")
    tx_id = await db.create_transaction(conn, body.user_id, body.category_id, body.amount, body.note)
    limit_warning = await db.get_limit_status(conn, body.user_id, body.category_id)
    return {"id": tx_id, "limit_warning": limit_warning}


@app.delete("/api/transactions/{tx_id}")
async def delete_transaction(tx_id: int, user_id: int, conn=Depends(get_conn)):
    if not await db.delete_transaction(conn, tx_id, user_id):
        raise HTTPException(404, "Transaction not found")
    return {"ok": True}


# ── Stats ──────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats(
    user_id: int,
    period: str = "month",
    year_month: str | None = None,
    conn=Depends(get_conn),
):
    import re
    if year_month and not re.match(r"^\d{4}-\d{2}$", year_month):
        raise HTTPException(400, "year_month must be YYYY-MM")
    if not year_month and period not in ("day", "week", "month"):
        raise HTTPException(400, "period must be day, week, or month")
    return await db.get_stats(conn, user_id, period, year_month)


# ── Categories — fixed routes before parameterised ─────────────────────────

@app.get("/api/categories/hidden")
async def list_hidden_categories(user_id: int, conn=Depends(get_conn)):
    return await db.get_hidden_categories(conn, user_id)


@app.get("/api/categories")
async def list_categories(user_id: int, type: str | None = None, conn=Depends(get_conn)):
    return await db.get_visible_categories(conn, user_id, type)


class CategoryCreate(BaseModel):
    user_id: int
    name: str
    type: str
    emoji: str = ""


@app.post("/api/categories", status_code=201)
async def create_category(body: CategoryCreate, conn=Depends(get_conn)):
    if body.type not in ("income", "expense"):
        raise HTTPException(400, "type must be income or expense")
    cat_id = await db.create_category(conn, body.user_id, body.name, body.type, body.emoji)
    return {"id": cat_id}


@app.delete("/api/categories/{category_id}")
async def delete_category(category_id: int, user_id: int, conn=Depends(get_conn)):
    if not await db.delete_category(conn, category_id, user_id):
        raise HTTPException(404, "Category not found or not owned by user")
    return {"ok": True}


@app.post("/api/categories/{category_id}/hide")
async def hide_category(category_id: int, user_id: int, conn=Depends(get_conn)):
    await db.hide_category(conn, user_id, category_id)
    return {"ok": True}


@app.post("/api/categories/{category_id}/unhide")
async def unhide_category(category_id: int, user_id: int, conn=Depends(get_conn)):
    await db.unhide_category(conn, user_id, category_id)
    return {"ok": True}


# ── Limits ─────────────────────────────────────────────────────────────────

class LimitSet(BaseModel):
    user_id: int
    category_id: int
    amount: float


@app.get("/api/limits")
async def list_limits(user_id: int, conn=Depends(get_conn)):
    return await db.get_limits(conn, user_id)


@app.post("/api/limits", status_code=201)
async def set_limit(body: LimitSet, conn=Depends(get_conn)):
    if body.amount <= 0:
        raise HTTPException(400, "amount must be > 0")
    await db.set_limit(conn, body.user_id, body.category_id, body.amount)
    return {"ok": True}


@app.delete("/api/limits/{category_id}")
async def delete_limit(category_id: int, user_id: int, conn=Depends(get_conn)):
    if not await db.delete_limit(conn, user_id, category_id):
        raise HTTPException(404, "Limit not found")
    return {"ok": True}


# ── Recurring ──────────────────────────────────────────────────────────────

class RecurringCreate(BaseModel):
    user_id: int
    category_id: int
    amount: float
    day_of_month: int


@app.get("/api/recurring")
async def list_recurring(user_id: int, conn=Depends(get_conn)):
    return await db.get_recurring(conn, user_id)


@app.post("/api/recurring", status_code=201)
async def create_recurring(body: RecurringCreate, conn=Depends(get_conn)):
    if not 1 <= body.day_of_month <= 31:
        raise HTTPException(400, "day_of_month must be 1–31")
    rec_id = await db.create_recurring(conn, body.user_id, body.category_id, body.amount, body.day_of_month)
    return {"id": rec_id}


@app.delete("/api/recurring/{rec_id}")
async def delete_recurring(rec_id: int, user_id: int, conn=Depends(get_conn)):
    if not await db.delete_recurring(conn, rec_id, user_id):
        raise HTTPException(404, "Recurring transaction not found")
    return {"ok": True}


# ── Serve frontend (must be last) ──────────────────────────────────────────

if os.path.exists("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
