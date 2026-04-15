"""add category parent_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "parent_id")
