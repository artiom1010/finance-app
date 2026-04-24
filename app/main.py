import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.v1 import (
    ai,
    auth,
    categories,
    health,
    limits,
    recurring,
    subscriptions,
    transactions,
    users,
    webhooks,
)
from app.core.config import settings
from app.core.telegram import fmt_http_error, notify
from app.services.subscription_expiry import run_forever as run_subscription_sweep

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Subscription expiry sweep — hourly backstop for missed EXPIRATION webhooks.
    sweep_task = asyncio.create_task(run_subscription_sweep())
    try:
        yield
    finally:
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="FinanceAI API",
    version=settings.app_version,
    lifespan=lifespan,
    # Swagger UI только в dev режиме
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — Flutter будет слать запросы с разных origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Middleware: логируем HTTP ошибки в Telegram ───────────────────
@app.middleware("http")
async def log_http_errors(request: Request, call_next):
    response = await call_next(request)
    if response.status_code >= 400:
        path = request.url.path
        # Не логируем OPTIONS preflight, health-check и сканеры ботов (404 вне /api/)
        if (
            request.method != "OPTIONS"
            and path != "/api/v1/health"
            and not (response.status_code == 404 and not path.startswith("/api/"))
        ):
            await notify(fmt_http_error(response.status_code, request.method, path))
    return response


# ── Роуты ─────────────────────────────────────────────────────────
app.include_router(health.router, prefix="/api/v1", tags=["system"])

app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(users.router, prefix="/api/v1", tags=["users"])
app.include_router(transactions.router, prefix="/api/v1", tags=["transactions"])
app.include_router(categories.router, prefix="/api/v1", tags=["categories"])
app.include_router(limits.router, prefix="/api/v1", tags=["limits"])
app.include_router(recurring.router, prefix="/api/v1", tags=["recurring"])
app.include_router(ai.router, prefix="/api/v1", tags=["ai"])
app.include_router(subscriptions.router, prefix="/api/v1", tags=["subscriptions"])
app.include_router(webhooks.router, prefix="/api/v1", tags=["webhooks"])
