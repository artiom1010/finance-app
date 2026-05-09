"""add budget_limits.alert_thresholds

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Three percent levels that trigger an in-app alert when a transaction
    # pushes `spent` past one of them. server_default backfills existing rows.
    op.add_column(
        "budget_limits",
        sa.Column(
            "alert_thresholds",
            JSONB,
            nullable=False,
            server_default=sa.text("'[50, 75, 100]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("budget_limits", "alert_thresholds")
