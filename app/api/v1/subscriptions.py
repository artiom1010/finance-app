"""Subscription endpoints exposed to authenticated clients.

`GET /subscriptions/me` — current state for UI gating.
`POST /subscriptions/sync` — client asks the server to authoritatively pull
fresh state from RevenueCat. This closes the race between a successful
purchase on-device and the webhook arriving: instead of waiting, the client
triggers an immediate server-side reconciliation.
"""
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.telegram import notify
from app.models.user import User
from app.schemas.user import SubscriptionResponse
from app.services import users as user_service
from app.services.subscriptions import (
    apply_subscription_update,
    fetch_revenuecat_snapshot,
    parse_revenuecat_snapshot,
)

router = APIRouter(prefix="/subscriptions")
limiter = Limiter(key_func=get_remote_address)


@router.get("/me", response_model=SubscriptionResponse)
async def get_my_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await user_service.get_subscription(user, db)


@router.post("/sync", response_model=SubscriptionResponse)
@limiter.limit("5/minute")
async def sync_subscription(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pull the authoritative subscription state from RevenueCat and apply it.

    Called by the client right after a successful purchase or restore. It is
    safe to retry: the update is idempotent and the cache-free pull always
    reflects the store's current view. Rate-limited to discourage abuse.
    """
    # RevenueCat app_user_id is the user's email (set via `Purchases.logIn`
    # in the Flutter client). This keeps the contract in one place.
    snapshot = await fetch_revenuecat_snapshot(user.email)
    update = parse_revenuecat_snapshot(snapshot)
    await apply_subscription_update(user, update, db, reason="client:sync")
    return await user_service.get_subscription(user, db)


class PurchaseAttempt(BaseModel):
    success: bool
    product_id: str | None = None
    error_code: str | None = None     # e.g. "purchase_cancelled", "network_error"
    error_message: str | None = None  # short human-readable reason


@router.post("/log-attempt", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def log_purchase_attempt(
    request: Request,
    payload: PurchaseAttempt,
    user: User = Depends(get_current_user),
):
    """Tell the server that the user just hit "buy" — used purely for Telegram
    visibility into purchase attempts. Failures here don't reach the RevenueCat
    webhook (Apple/Google never confirm them), so this is the only signal we
    have for "user tried to pay and was declined / cancelled".
    """
    if payload.success:
        title = "🟢 <b>Покупка подтверждена клиентом</b>"
    else:
        # Distinguish a deliberate cancel from a real failure — a cancel is
        # noise, a failure is something I might want to investigate.
        if payload.error_code == "purchase_cancelled":
            title = "⚪ <b>Покупка отменена пользователем</b>"
        else:
            title = "🔴 <b>Сбой покупки</b>"
    lines = [title, f"📧 {user.email}"]
    if payload.product_id:
        lines.append(f"📦 {payload.product_id}")
    if payload.error_message:
        lines.append(f"📝 {payload.error_message}")
    elif payload.error_code:
        lines.append(f"📝 {payload.error_code}")
    await notify("\n".join(lines))
