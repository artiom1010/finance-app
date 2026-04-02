from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, health
from app.core.config import settings

app = FastAPI(
    title="FinanceAI API",
    version=settings.app_version,
    # Swagger UI только в dev режиме
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# CORS — Flutter будет слать запросы с разных origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Роуты ─────────────────────────────────────────────────────────
app.include_router(health.router, prefix="/api/v1", tags=["system"])

app.include_router(auth.router, prefix="/api/v1", tags=["auth"])

# Сюда будем добавлять по мере разработки:
# app.include_router(transactions.router, prefix="/api/v1", tags=["transactions"])
# app.include_router(categories.router,   prefix="/api/v1", tags=["categories"])
# app.include_router(limits.router,       prefix="/api/v1", tags=["limits"])
# app.include_router(ai.router,           prefix="/api/v1", tags=["ai"])
