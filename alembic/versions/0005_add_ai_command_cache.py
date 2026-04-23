"""add ai_command_cache

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_command_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("data_hash", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "command", name="uq_ai_command_cache_user_cmd"),
    )
    op.create_index(
        "ix_ai_command_cache_user_expires",
        "ai_command_cache",
        ["user_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_command_cache_user_expires", table_name="ai_command_cache")
    op.drop_table("ai_command_cache")
