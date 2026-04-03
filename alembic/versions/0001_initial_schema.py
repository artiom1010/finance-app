"""initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-04-03

Полная начальная схема + системные данные.
Запускается на пустой БД при первом деплое на VPS.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Пользователи ──────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(), unique=True, nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("first_name", sa.String(), nullable=False),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "auth_providers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_auth_providers_provider_user"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(), unique=True, nullable=False),
        sa.Column("device_id", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_refresh_tokens_user_active", "refresh_tokens", ["user_id"],
                    postgresql_where=sa.text("revoked_at IS NULL"))

    # ── Валюты ────────────────────────────────────────────────────────────────
    op.create_table(
        "currencies",
        sa.Column("code", sa.String(3), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(5), nullable=False),
    )
    op.execute("""
        INSERT INTO currencies (code, name, symbol) VALUES
        ('USD', 'US Dollar',         '$'),
        ('EUR', 'Euro',              '€'),
        ('GBP', 'British Pound',     '£'),
        ('RUB', 'Russian Ruble',     '₽'),
        ('KZT', 'Kazakhstani Tenge', '₸'),
        ('CNY', 'Chinese Yuan',      '¥'),
        ('AED', 'UAE Dirham',        'د.إ'),
        ('JPY', 'Japanese Yen',      '¥'),
        ('TRY', 'Turkish Lira',      '₺'),
        ('INR', 'Indian Rupee',      '₹')
    """)

    # ── Темы ──────────────────────────────────────────────────────────────────
    op.create_table(
        "themes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(), unique=True, nullable=False),
    )
    op.execute("""
        INSERT INTO themes (id, name) VALUES
        (gen_random_uuid(), 'light'),
        (gen_random_uuid(), 'dark'),
        (gen_random_uuid(), 'midnight'),
        (gen_random_uuid(), 'forest'),
        (gen_random_uuid(), 'rose'),
        (gen_random_uuid(), 'ocean')
    """)

    # ── Настройки пользователя ────────────────────────────────────────────────
    op.create_table(
        "user_settings",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("currency_code", sa.String(), sa.ForeignKey("currencies.code"), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("theme_id", UUID(as_uuid=True), sa.ForeignKey("themes.id"), nullable=False),
        sa.Column("font_size", sa.String(), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("language", sa.String(), nullable=False, server_default=sa.text("'en'")),
        sa.Column("week_starts_on", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── Подписки ──────────────────────────────────────────────────────────────
    op.create_table(
        "subscriptions",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tier", sa.String(), nullable=False, server_default=sa.text("'free'")),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("store", sa.String(), nullable=True),
        sa.Column("revenuecat_customer_id", sa.String(), unique=True, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── Категории ─────────────────────────────────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False, server_default=sa.text("'💰'")),
        sa.Column("color", sa.String(), nullable=False, server_default=sa.text("'#6B7280'")),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_categories_user_id", "categories", ["user_id"])
    op.execute("""
        INSERT INTO categories (id, user_id, name, icon, color, type, sort_order) VALUES
        (gen_random_uuid(), NULL, 'Food & Drinks',  '🍔', '#F59E0B', 'expense', 1),
        (gen_random_uuid(), NULL, 'Transport',      '🚗', '#3B82F6', 'expense', 2),
        (gen_random_uuid(), NULL, 'Shopping',       '🛍️', '#EC4899', 'expense', 3),
        (gen_random_uuid(), NULL, 'Housing',        '🏠', '#8B5CF6', 'expense', 4),
        (gen_random_uuid(), NULL, 'Health',         '💊', '#EF4444', 'expense', 5),
        (gen_random_uuid(), NULL, 'Entertainment',  '🎮', '#F97316', 'expense', 6),
        (gen_random_uuid(), NULL, 'Education',      '📚', '#06B6D4', 'expense', 7),
        (gen_random_uuid(), NULL, 'Travel',         '✈️', '#10B981', 'expense', 8),
        (gen_random_uuid(), NULL, 'Subscriptions',  '📱', '#6366F1', 'expense', 9),
        (gen_random_uuid(), NULL, 'Other',          '📦', '#6B7280', 'expense', 10),
        (gen_random_uuid(), NULL, 'Salary',         '💼', '#22C55E', 'income',  1),
        (gen_random_uuid(), NULL, 'Freelance',      '💻', '#84CC16', 'income',  2),
        (gen_random_uuid(), NULL, 'Investments',    '📈', '#14B8A6', 'income',  3),
        (gen_random_uuid(), NULL, 'Gift',           '🎁', '#F472B6', 'income',  4),
        (gen_random_uuid(), NULL, 'Other Income',   '💰', '#A3E635', 'income',  5)
    """)

    # ── Транзакции ────────────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_transactions_user_date", "transactions", ["user_id", "date"])
    op.create_index("ix_transactions_user_deleted", "transactions", ["user_id", "deleted_at"])

    # ── AI ────────────────────────────────────────────────────────────────────
    op.create_table(
        "ai_prompt_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("prompt", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False, server_default=sa.text("'💡'")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.execute("""
        INSERT INTO ai_prompt_templates (id, label, prompt, icon, sort_order) VALUES
        (
            gen_random_uuid(),
            'Insights for last month',
            'Analyze my expenses for last month. Which categories grew? Any anomalies? Give me 2-3 specific observations.',
            '📊', 1
        ),
        (
            gen_random_uuid(),
            'How to start saving?',
            'Look at my income and expenses for the last 2 months. How much can I realistically save and where do I start?',
            '🏦', 2
        ),
        (
            gen_random_uuid(),
            'Where does my money go?',
            'Explain simply: what am I spending money on and why do I have nothing left at the end of the month? Be specific and honest.',
            '🔍', 3
        )
    """)

    op.create_table(
        "ai_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("prompt_template_id", UUID(as_uuid=True), sa.ForeignKey("ai_prompt_templates.id"), nullable=True),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ai_messages_user_cleared", "ai_messages", ["user_id", "cleared_at"])

    op.create_table(
        "ai_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("user_id", "date", name="uq_ai_usage_user_date"),
    )


def downgrade() -> None:
    op.drop_table("ai_usage")
    op.drop_table("ai_messages")
    op.drop_table("ai_prompt_templates")
    op.drop_table("transactions")
    op.drop_table("categories")
    op.drop_table("subscriptions")
    op.drop_table("user_settings")
    op.drop_table("themes")
    op.drop_table("currencies")
    op.drop_table("refresh_tokens")
    op.drop_table("auth_providers")
    op.drop_table("users")
