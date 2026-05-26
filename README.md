# FinanceAI

Personal finance app with an AI-powered advisor. Free/Pro freemium model via RevenueCat.

**Status:** post-MVP, closed-beta ready. ~90% of [plan/start.txt](plan/start.txt) shipped; ~65% of the strategic plan in [plan/FinanceAI_Plan.html](plan/FinanceAI_Plan.html).

## Stack

- **Backend:** FastAPI (Python 3.12) + SQLAlchemy 2 (asyncpg) + Alembic
- **Mobile:** Flutter 3.11+ with Riverpod + go_router + dio + fl_chart
- **DB:** PostgreSQL 16
- **AI:** Anthropic Claude Haiku 4.5
- **Payments:** RevenueCat (iOS IAP, webhook + REST sync)
- **Auth:** email/password + Google OAuth (Web + iOS audiences) + Apple Sign In (backend only — Flutter UI pending)
- **Logging:** Telegram bot (signup, login, first tx, AI calls, payments, 4xx/5xx)

## Repository layout

| Path | Purpose |
|---|---|
| [app/](app/) | FastAPI backend (routers, models, services, core) |
| [alembic/](alembic/) | DB migrations (7 revisions: 0001 → 0007) |
| [tests/](tests/) | pytest-asyncio suite (auth, users, transactions, categories, ai) |
| [mobile/](mobile/) | Flutter app (8 feature screens) |
| [fin-app(c-design)/](fin-app(c-design)/) | HTML/CSS prototypes from Claude Design — UI reference |
| [plan/](plan/) | Strategic + operational plans (HTML + txt) |
| [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml) | Container runtime |

## Backend API (v1)

Mounted under `/api/v1`. Routers in [app/api/v1/](app/api/v1/):

- `auth` — register, login (email + Google + Apple), refresh, logout, sessions
- `users` — profile, settings (lang/currency/theme/font/notifications), delete account
- `transactions` — CRUD, filters, pagination, statistics, CSV export
- `categories` — CRUD, hierarchy via `parent_id`, system + user copies
- `limits` — budget limits with 50/75/100% alert thresholds (Pro)
- `recurring` — recurring transactions CRUD (Pro) — **note: no auto-scheduler yet**
- `ai` — 3 fixed commands (headline, overshoot, cuts), 24h cache, weekly free / 3-per-day Pro quota
- `subscriptions` — RevenueCat sync + hourly expiry sweep
- `webhooks` — RevenueCat events (INITIAL_PURCHASE, RENEWAL, EXPIRATION, REFUND, ...)
- `health` — DB ping + version

Rate limit: 10 req/min on `/ai/command`. AI daily soft cap: `$5 USD` (returns 503 + Telegram alert).

## Local development

### Backend

```bash
cp .env.example .env        # fill in secrets (see comments inside)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Migrations run on container start. API at `http://localhost:8000`, docs at `/docs`.

### Mobile

See [mobile/README.md](mobile/README.md).

### Tests

```bash
uv run pytest                # or: pip install -e ".[dev]" && pytest
```

## What's left before production

See [plan/start.txt](plan/start.txt) for the full 7-stage MVP plan with status markers.

- [ ] **CI/CD** — no `.github/workflows/` yet (Stage 4 of start.txt — skipped)
- [ ] **Apple Sign In in Flutter** — backend ready, mobile shows "in development" SnackBar
- [ ] **Recurring tx auto-execution** — model + CRUD exist, scheduler missing
- [ ] **Production monitoring** — Sentry / Prometheus not wired; Telegram-only today
- [ ] **Feature flags (PostHog)** — strategic plan calls for it, not implemented
