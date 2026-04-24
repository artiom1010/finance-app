"""Backstop that auto-downgrades subscriptions whose `expires_at` passed.

The RevenueCat webhook is the authoritative source for state changes, but
it can be dropped, delayed, or misconfigured. We sweep the DB every hour and
forcibly transition any active/cancelled Pro subscriptions past their
deadline to free/expired. Without this, a single missed EXPIRATION webhook
would grant a user lifetime Pro access.

This runs in-process via FastAPI's lifespan (wired up elsewhere) — no
external scheduler required.
"""
import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.user import Subscription

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL_SECONDS = 3600  # 1h
# States we consider "still granting Pro" that must be checked against the
# expiration date. Anything not in this set has already been downgraded.
_ACTIVE_STATES = ("active", "trialing", "grace_period", "cancelled")


async def expire_overdue(db: AsyncSession) -> int:
    """Downgrade all subscriptions whose `expires_at` is in the past.

    Returns the number of rows updated. Safe to call concurrently — the
    individual row updates are idempotent.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(Subscription).where(
            Subscription.tier == "pro",
            Subscription.status.in_(_ACTIVE_STATES),
            Subscription.expires_at.is_not(None),
            Subscription.expires_at <= now,
        )
    )
    overdue = result.scalars().all()
    for sub in overdue:
        logger.info(
            "sub_expired user=%s prev=%s/%s expires_at=%s",
            sub.user_id, sub.tier, sub.status, sub.expires_at,
        )
        sub.tier = "free"
        sub.status = "expired"
    if overdue:
        await db.commit()
    return len(overdue)


async def run_forever() -> None:
    """Background task: sweep once per hour until cancelled."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                count = await expire_overdue(db)
            if count:
                logger.info("subscription expiry sweep downgraded %d", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("subscription expiry sweep failed")
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
