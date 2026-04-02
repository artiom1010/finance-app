from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    # Проверяем что база отвечает
    await db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "version": settings.app_version,
        "env": settings.app_env,
        "database": "connected",
    }
