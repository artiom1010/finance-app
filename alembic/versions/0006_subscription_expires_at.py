"""add subscriptions.expires_at

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_subscriptions_status_expires_at",
        "subscriptions",
        ["status", "expires_at"],
    )
    # Grace period for existing active Pro subscribers so they don't get
    # immediately downgraded by the expiry cron before a webhook arrives.
    op.execute(
        "UPDATE subscriptions "
        "SET expires_at = now() + interval '30 days' "
        "WHERE tier = 'pro' AND status IN ('active', 'trialing') "
        "AND expires_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_status_expires_at", table_name="subscriptions")
    op.drop_column("subscriptions", "expires_at")
