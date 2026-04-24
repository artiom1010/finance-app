"""Subscription state management.

Single source of truth for writing to the `subscriptions` table. Both the
RevenueCat webhook and the client-triggered `/subscriptions/sync` endpoint
funnel through `apply_subscription_update` so there's exactly one audit log
and one place to evolve the schema.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import Subscription, User

logger = logging.getLogger(__name__)

_PRO_STATES = ("active", "trialing", "grace_period", "cancelled")

# Mirrors the mapping used by the webhook — kept here so sync can reuse it.
_STORE_FROM_CODE: dict[str, str] = {
    "APP_STORE": "app_store",
    "MAC_APP_STORE": "app_store",
    "PLAY_STORE": "google_play",
    "STRIPE": "stripe",
    "PROMOTIONAL": "promotional",
    "app_store": "app_store",
    "mac_app_store": "app_store",
    "play_store": "google_play",
    "stripe": "stripe",
    "promotional": "promotional",
}


@dataclass
class SubscriptionUpdate:
    tier: str
    status: str
    expires_at: datetime | None = None
    store: str | None = None
    revenuecat_customer_id: str | None = None


async def apply_subscription_update(
    user: User,
    update: SubscriptionUpdate,
    db: AsyncSession,
    *,
    reason: str,
) -> Subscription:
    """Upsert the user's subscription state from a trusted source.

    Callers: RevenueCat webhook, `/subscriptions/sync`, manual admin ops,
    expiry cron. `reason` is logged for audit.
    """
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        sub = Subscription(user_id=user.id)
        db.add(sub)

    prev_tier, prev_status = sub.tier, sub.status
    sub.tier = update.tier
    sub.status = update.status
    # expires_at is unconditionally written: callers explicitly pass None on
    # expiration/refund to clear the prior deadline.
    sub.expires_at = update.expires_at
    if update.store:
        sub.store = update.store
    if update.revenuecat_customer_id:
        sub.revenuecat_customer_id = update.revenuecat_customer_id

    await db.commit()
    logger.info(
        "sub_update user=%s reason=%s %s/%s -> %s/%s expires=%s",
        user.id, reason, prev_tier, prev_status, sub.tier, sub.status,
        sub.expires_at,
    )
    return sub


def is_effective_pro(sub: Subscription | None) -> bool:
    """Check whether the subscription entitles the user to Pro right now.

    Trust the DB: tier must be 'pro', status in an active state, and the
    `expires_at` (if set) must be in the future. `expires_at is None` is
    treated as "no deadline known" — allowed, because backfill of long-term
    test accounts and promotional grants don't carry an expiry.
    """
    if sub is None or sub.tier != "pro":
        return False
    if sub.status not in _PRO_STATES:
        return False
    if sub.expires_at is not None and sub.expires_at <= datetime.now(UTC):
        return False
    return True


# ── RevenueCat REST client ────────────────────────────────────────────
# Public ref: https://www.revenuecat.com/docs/api-v1
# We only need the `GET /v1/subscribers/{app_user_id}` endpoint, which
# returns the authoritative entitlements snapshot.

_RC_API_BASE = "https://api.revenuecat.com/v1"
_RC_PRO_ENTITLEMENT = "pro"


async def fetch_revenuecat_snapshot(app_user_id: str) -> dict[str, Any]:
    """Pull the latest subscription snapshot directly from RevenueCat.

    Raises HTTPException(503) if the server has no REST key configured, or
    if RevenueCat is unreachable/returning 5xx.
    """
    api_key = settings.revenuecat_rest_api_key
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription sync is not configured",
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{_RC_API_BASE}/subscribers/{app_user_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError as exc:
        logger.warning("revenuecat sync network error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach subscription service",
        ) from exc

    if r.status_code == 404:
        # Unknown subscriber — treat as no purchase yet.
        return {}
    if r.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription service returned an error",
        )
    if r.status_code >= 400:
        logger.warning("revenuecat sync %s: %s", r.status_code, r.text[:200])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Subscription service rejected the request",
        )
    return r.json()


def parse_revenuecat_snapshot(payload: dict[str, Any]) -> SubscriptionUpdate:
    """Project RevenueCat's subscriber payload down to our update shape.

    Picks the `pro` entitlement's expiration as the source of truth.
    Falls back to free/expired if there is no active pro entitlement.
    """
    subscriber = payload.get("subscriber") or {}
    entitlements = subscriber.get("entitlements") or {}
    pro = entitlements.get(_RC_PRO_ENTITLEMENT)

    now = datetime.now(UTC)
    if pro:
        expires_iso = pro.get("expires_date")
        expires_at = _parse_iso(expires_iso)
        if expires_at is None or expires_at > now:
            # Active pro entitlement.
            subscriptions_map = subscriber.get("subscriptions") or {}
            product_id = pro.get("product_identifier")
            sub_info = (subscriptions_map.get(product_id) or {}) if product_id else {}
            store_code = sub_info.get("store")
            return SubscriptionUpdate(
                tier="pro",
                status="active",
                expires_at=expires_at,
                store=_STORE_FROM_CODE.get(store_code or ""),
                revenuecat_customer_id=subscriber.get("original_app_user_id"),
            )

    # No active pro entitlement — downgrade to free.
    return SubscriptionUpdate(
        tier="free",
        status="expired",
        expires_at=None,
        store=None,
        revenuecat_customer_id=subscriber.get("original_app_user_id"),
    )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # RevenueCat returns "2026-05-01T12:34:56Z" or with millis.
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
