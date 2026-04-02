-- ============================================================
-- FinanceAI — Initial Migration
-- Version: 001
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- БЛОК 1: АУТЕНТИФИКАЦИЯ
-- ────────────────────────────────────────────────────────────

CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT,                        -- NULL для OAuth пользователей
    first_name    TEXT NOT NULL,
    last_name     TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Один пользователь может войти через Google И Apple
CREATE TABLE auth_providers (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider         TEXT NOT NULL CHECK (provider IN ('google', 'apple')),
    provider_user_id TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_user_id)
);

-- Храним хэш токена, не сам токен
CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT UNIQUE NOT NULL,
    device_id   TEXT,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,                   -- NULL = активен
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- FCM — один пользователь, несколько устройств
CREATE TABLE push_tokens (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token        TEXT UNIQUE NOT NULL,
    platform     TEXT NOT NULL CHECK (platform IN ('ios', 'android')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ────────────────────────────────────────────────────────────
-- БЛОК 2: НАСТРОЙКИ
-- ────────────────────────────────────────────────────────────

-- Справочник валют ISO 4217 (системные данные)
CREATE TABLE currencies (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    symbol_position TEXT NOT NULL DEFAULT 'before' CHECK (symbol_position IN ('before', 'after')),
    decimal_places  INT  NOT NULL DEFAULT 2
);

INSERT INTO currencies (code, name, symbol, symbol_position, decimal_places) VALUES
    ('USD', 'US Dollar',         '$',   'before', 2),
    ('EUR', 'Euro',              '€',   'before', 2),
    ('GBP', 'British Pound',     '£',   'before', 2),
    ('RUB', 'Russian Ruble',     '₽',   'after',  2),
    ('KZT', 'Kazakhstani Tenge', '₸',   'after',  2),
    ('CNY', 'Chinese Yuan',      '¥',   'before', 2),
    ('AED', 'UAE Dirham',        'د.إ', 'after',  2),
    ('JPY', 'Japanese Yen',      '¥',   'before', 0),
    ('TRY', 'Turkish Lira',      '₺',   'before', 2),
    ('INR', 'Indian Rupee',      '₹',   'before', 2);

-- 6 системных тем, light — бесплатная, остальные pro
CREATE TABLE themes (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT UNIQUE NOT NULL,
    is_pro     BOOLEAN NOT NULL DEFAULT false,
    sort_order INT NOT NULL DEFAULT 0
);

INSERT INTO themes (name, is_pro, sort_order) VALUES
    ('light',    false, 1),
    ('dark',     true,  2),
    ('midnight', true,  3),
    ('forest',   true,  4),
    ('rose',     true,  5),
    ('ocean',    true,  6);

-- Настройки пользователя (1:1 с users)
CREATE TABLE user_settings (
    user_id               UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    currency_code         TEXT NOT NULL DEFAULT 'USD' REFERENCES currencies(code),
    theme_id              UUID NOT NULL REFERENCES themes(id),
    font_size             TEXT NOT NULL DEFAULT 'medium' CHECK (font_size IN ('small', 'medium', 'large')),
    language              TEXT NOT NULL DEFAULT 'en',
    week_starts_on        INT  NOT NULL DEFAULT 1 CHECK (week_starts_on IN (0, 1)),
    notifications_enabled BOOLEAN NOT NULL DEFAULT true,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ────────────────────────────────────────────────────────────
-- БЛОК 3: ПОДПИСКИ
-- ────────────────────────────────────────────────────────────

CREATE TABLE subscriptions (
    user_id                UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    tier                   TEXT NOT NULL DEFAULT 'free' CHECK (tier IN ('free', 'pro')),
    status                 TEXT NOT NULL DEFAULT 'active'
                               CHECK (status IN ('active', 'trialing', 'cancelled', 'expired', 'paused')),
    store                  TEXT CHECK (store IN ('app_store', 'google_play', 'web')),
    revenuecat_customer_id TEXT UNIQUE,
    product_id             TEXT,
    trial_ends_at          TIMESTAMPTZ,
    current_period_start   TIMESTAMPTZ,
    current_period_end     TIMESTAMPTZ,           -- NULL = free навсегда
    cancelled_at           TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Лог всех вебхуков RevenueCat — никогда не удаляется
CREATE TABLE subscription_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type          TEXT NOT NULL,
    store               TEXT,
    product_id          TEXT,
    price_usd           NUMERIC(10, 2),
    revenuecat_event_id TEXT UNIQUE,             -- дедупликация вебхуков
    raw_payload         JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Счётчики freemium (50 транзакций/мес для free)
CREATE TABLE free_tier_usage (
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    year_month         TEXT NOT NULL,             -- формат 'YYYY-MM'
    transactions_count INT  NOT NULL DEFAULT 0,
    UNIQUE (user_id, year_month)
);


-- ────────────────────────────────────────────────────────────
-- БЛОК 4: ФИНАНСЫ
-- ────────────────────────────────────────────────────────────

-- user_id = NULL → системная категория (15 предустановленных)
CREATE TABLE categories (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    icon       TEXT NOT NULL DEFAULT '💰',
    color      TEXT NOT NULL DEFAULT '#6B7280',
    type       TEXT NOT NULL CHECK (type IN ('expense', 'income', 'both')),
    is_active  BOOLEAN NOT NULL DEFAULT true,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

-- Системные категории (user_id = NULL)
INSERT INTO categories (user_id, name, icon, color, type, sort_order) VALUES
    (NULL, 'Food & Drinks',   '🍔', '#F59E0B', 'expense', 1),
    (NULL, 'Transport',       '🚗', '#3B82F6', 'expense', 2),
    (NULL, 'Shopping',        '🛍️', '#EC4899', 'expense', 3),
    (NULL, 'Housing',         '🏠', '#8B5CF6', 'expense', 4),
    (NULL, 'Health',          '💊', '#EF4444', 'expense', 5),
    (NULL, 'Entertainment',   '🎮', '#F97316', 'expense', 6),
    (NULL, 'Education',       '📚', '#06B6D4', 'expense', 7),
    (NULL, 'Travel',          '✈️', '#10B981', 'expense', 8),
    (NULL, 'Subscriptions',   '📱', '#6366F1', 'expense', 9),
    (NULL, 'Other',           '📦', '#6B7280', 'expense', 10),
    (NULL, 'Salary',          '💼', '#22C55E', 'income',  1),
    (NULL, 'Freelance',       '💻', '#84CC16', 'income',  2),
    (NULL, 'Investments',     '📈', '#14B8A6', 'income',  3),
    (NULL, 'Gift',            '🎁', '#F472B6', 'income',  4),
    (NULL, 'Other Income',    '💰', '#A3E635', 'income',  5);

-- Главная таблица продукта
-- NUMERIC(15,2) — никогда не float для денег
-- deleted_at — мягкое удаление (финансовые данные не уничтожаем)
CREATE TABLE transactions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES categories(id),
    amount      NUMERIC(15, 2) NOT NULL CHECK (amount > 0),
    type        TEXT NOT NULL CHECK (type IN ('expense', 'income')),
    note        TEXT,
    date        DATE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ                        -- NULL = активна
);

CREATE TABLE spending_limits (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    amount      NUMERIC(15, 2) NOT NULL CHECK (amount > 0),
    period      TEXT NOT NULL DEFAULT 'monthly' CHECK (period IN ('monthly', 'weekly')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, category_id, period)
);

-- Один алерт на порог за период — UNIQUE гарантирует это (ACID Consistency)
CREATE TABLE limit_alerts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spending_limit_id UUID NOT NULL REFERENCES spending_limits(id) ON DELETE CASCADE,
    threshold_percent INT NOT NULL CHECK (threshold_percent IN (80, 100)),
    period_start      DATE NOT NULL,
    alerted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (spending_limit_id, threshold_percent, period_start)
);


-- ────────────────────────────────────────────────────────────
-- БЛОК 5: AI СОВЕТНИК
-- ────────────────────────────────────────────────────────────

-- Один чат на пользователя, без conversations
-- cleared_at — мягкая очистка чата (история не теряется)
CREATE TABLE ai_messages (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role               TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    prompt_template_id UUID,                      -- NULL = ручной ввод
    content            TEXT NOT NULL,
    tokens_used        INT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at         TIMESTAMPTZ                -- NULL = видно в чате
);

-- Дневной лимит: 5 запросов для free, безлимит для pro
-- Данные пишем для всех — аналитика стоимости
CREATE TABLE ai_usage (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date          DATE NOT NULL DEFAULT CURRENT_DATE,
    request_count INT  NOT NULL DEFAULT 0,
    UNIQUE (user_id, date)
);

-- Системные кнопки-вопросы (обновляются без релиза приложения)
CREATE TABLE ai_prompt_templates (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label      TEXT NOT NULL,
    prompt     TEXT NOT NULL,
    icon       TEXT NOT NULL DEFAULT '💡',
    sort_order INT  NOT NULL DEFAULT 0,
    is_active  BOOLEAN NOT NULL DEFAULT true
);

INSERT INTO ai_prompt_templates (label, prompt, icon, sort_order) VALUES
    (
        'Insights for last month',
        'Analyze my expenses for last month. Which categories grew? Any anomalies? Give me 2-3 specific observations.',
        '📊', 1
    ),
    (
        'How to start saving?',
        'Look at my income and expenses for the last 2 months. How much can I realistically save and where do I start?',
        '🏦', 2
    ),
    (
        'Where does my money go?',
        'Explain simply: what am I spending money on and why do I have nothing left at the end of the month? Be specific and honest.',
        '🔍', 3
    );

-- FK из ai_messages на ai_prompt_templates (добавляем после создания обеих таблиц)
ALTER TABLE ai_messages
    ADD CONSTRAINT fk_ai_messages_template
    FOREIGN KEY (prompt_template_id) REFERENCES ai_prompt_templates(id);


-- ────────────────────────────────────────────────────────────
-- ИНДЕКСЫ
-- ────────────────────────────────────────────────────────────

CREATE INDEX idx_transactions_user_date
    ON transactions(user_id, date DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_transactions_user_category
    ON transactions(user_id, category_id)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_categories_user
    ON categories(user_id)
    WHERE is_active = true;

CREATE INDEX idx_spending_limits_user
    ON spending_limits(user_id);

CREATE INDEX idx_ai_messages_user
    ON ai_messages(user_id, created_at)
    WHERE cleared_at IS NULL;

CREATE INDEX idx_ai_usage_user_date
    ON ai_usage(user_id, date);

CREATE INDEX idx_subscription_events_user
    ON subscription_events(user_id, created_at DESC);

CREATE INDEX idx_free_tier_usage_user
    ON free_tier_usage(user_id, year_month);

CREATE INDEX idx_refresh_tokens_user
    ON refresh_tokens(user_id)
    WHERE revoked_at IS NULL;
