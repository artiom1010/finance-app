from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.v1 import ai, auth, categories, health, limits, recurring, transactions, users
from app.core.config import settings
from app.core.telegram import fmt_http_error, notify

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="FinanceAI API",
    version=settings.app_version,
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
        # Не логируем OPTIONS preflight и health-check
        if request.method != "OPTIONS" and request.url.path != "/api/v1/health":
            await notify(fmt_http_error(response.status_code, request.method, request.url.path))
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
