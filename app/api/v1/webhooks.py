"""Server-to-server webhooks received from external services.

Currently only RevenueCat is handled here. The endpoint is public (no JWT)
but protected by a shared secret sent as an `Authorization: Bearer <secret>`
header configured in the RevenueCat dashboard.
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import Subscription, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks")


# ── Event → (tier, status) mapping ────────────────────────────────────
# Reference: https://www.revenuecat.com/docs/webhooks#event-types
_TIER_FROM_EVENT: dict[str, tuple[str, str]] = {
    "INITIAL_PURCHASE":  ("pro",  "active"),
    "RENEWAL":           ("pro",  "active"),
    "PRODUCT_CHANGE":    ("pro",  "active"),
    "UNCANCELLATION":    ("pro",  "active"),
    "CANCELLATION":      ("pro",  "cancelled"),   # still Pro until expiration
    "EXPIRATION":        ("free", "expired"),
    "BILLING_ISSUE":     ("pro",  "grace_period"),
    "SUBSCRIPTION_PAUSED": ("free", "paused"),
}

_STORE_FROM_EVENT: dict[str, str] = {
    "APP_STORE":     "app_store",
    "MAC_APP_STORE": "app_store",
    "PLAY_STORE":    "google_play",
    "STRIPE":        "stripe",
    "PROMOTIONAL":   "promotional",
}


def _verify_secret(authorization: str | None) -> None:
    """Reject the request unless `Authorization: Bearer <secret>` matches."""
    expected = settings.revenuecat_webhook_secret
    if not expected:
        # Refuse to accept anything if the server has no secret configured
        # — avoids a deploy accidentally accepting unsigned events.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


async def _resolve_user(
    event: dict[str, Any],
    db: AsyncSession,
) -> User | None:
    """Find the User this event belongs to.

    Accepts both the RevenueCat `app_user_id` (set via `Purchases.logIn` on
    the client) and any `aliases` list RevenueCat sends. We treat the value
    as the user's email because that's what the Flutter client passes today.
    """
    candidates: list[str] = []
    app_user_id = event.get("app_user_id")
    if app_user_id:
        candidates.append(str(app_user_id))
    aliases = event.get("aliases") or []
    candidates.extend(str(a) for a in aliases if a)
    if not candidates:
        return None

    result = await db.execute(select(User).where(User.email.in_(candidates)))
    return result.scalar_one_or_none()


@router.post("/revenuecat", status_code=status.HTTP_204_NO_CONTENT)
async def revenuecat_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Receive subscription lifecycle events from RevenueCat.

    We keep this endpoint idempotent by design — each event is a snapshot of
    the current state, and we always write the latest mapping instead of
    accumulating history. RevenueCat retries on non-2xx, so on unexpected
    errors we return 500 and let them retry.
    """
    _verify_secret(authorization)

    payload = await request.json()
    event = payload.get("event") or {}
    event_type = event.get("type")
    if not event_type:
        raise HTTPException(status_code=400, detail="Missing event.type")

    user = await _resolve_user(event, db)
    if user is None:
        # Non-existent user can happen during testing or if a purchase runs
        # under an anonymous id that never logged in. 204 still — we don't
        # want RevenueCat to keep retrying a missing user.
        logger.info("revenuecat event %s for unknown user_id=%s",
                    event_type, event.get("app_user_id"))
        return

    mapping = _TIER_FROM_EVENT.get(event_type)
    if mapping is None:
        # Unknown / uninteresting event — log and ack.
        logger.info("revenuecat event ignored: %s", event_type)
        return
    tier, sub_status = mapping

    # Upsert subscription row
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        sub = Subscription(user_id=user.id)
        db.add(sub)

    sub.tier = tier
    sub.status = sub_status

    store_code = event.get("store")
    if store_code and store_code in _STORE_FROM_EVENT:
        sub.store = _STORE_FROM_EVENT[store_code]

    # RevenueCat identifies the subscriber by `app_user_id` we sent at login
    # time, and additionally assigns a stable `original_app_user_id`. We
    # persist the latter when available for future reconciliation.
    rc_customer_id = (
        event.get("original_app_user_id")
        or event.get("app_user_id")
    )
    if rc_customer_id:
        sub.revenuecat_customer_id = str(rc_customer_id)

    await db.commit()
    logger.info(
        "revenuecat %s: user=%s tier=%s status=%s store=%s",
        event_type, user.id, tier, sub_status, sub.store,
    )
