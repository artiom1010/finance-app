"""AI service — fixed-command Claude integration with caching and budget guard.

Design decisions (see `/Users/artemsary/.claude/plans/linear-wishing-bengio.md`):
- No free-form chat. Only three commands: headline / overshoot / cuts.
- Each command: max_tokens=400, no history, compact transaction summary.
- 24h cache per (user, command) keyed by a hash of the input data.
- Daily limits: Free = 1 command, Pro = 3 commands. Counts only cache misses.
- Global daily USD budget guard with Telegram alert.
"""
import hashlib
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, date as Date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.telegram import notify
from app.models.ai import AiCommandCache, AiMessage, AiUsage
from app.models.transaction import Category, Transaction
from app.models.user import User
from app.schemas.ai import (
    AiCommand,
    AiCommandResponse,
    AiTemplateDescriptor,
    AiUsageResponse,
)

logger = logging.getLogger(__name__)

# ── Limits ───────────────────────────────────────────────────────────
FREE_COMMAND_LIMIT = 1
PRO_COMMAND_LIMIT = 3
CACHE_TTL = timedelta(hours=24)
REQUEST_TIMEOUT_SECONDS = 15.0
MAX_OUTPUT_TOKENS = 400

# Haiku 4.5 pricing (USD per 1M tokens); used for soft daily budget check.
HAIKU_INPUT_COST_PER_1M = 0.8
HAIKU_OUTPUT_COST_PER_1M = 4.0

# ── Prompts ──────────────────────────────────────────────────────────
_PROMPTS: dict[AiCommand, str] = {
    "headline": (
        "Ты — личный финансовый наставник в мобильном приложении FinanceAI. "
        "Напиши короткое наблюдение о месяце пользователя: баланс, самая крупная "
        "категория расходов и одно ощущение от картины. 2-3 коротких предложения, "
        "человечная интонация, без списков и без осуждения. Не повторяй цифры "
        "рядом несколько раз."
    ),
    "overshoot": (
        "Ты — внимательный финансовый наставник в приложении FinanceAI. Сравни "
        "текущий месяц с предыдущим и укажи 1-2 категории, где траты заметно "
        "выросли. Укажи на сколько примерно и добавь одну фразу поддержки. "
        "Короткий текст, без списков, без драмы."
    ),
    "cuts": (
        "Ты — мягкий, но практичный финансовый наставник. Предложи ровно 3 "
        "конкретных шага, которые помогут пользователю сократить расходы в этом "
        "месяце, исходя из его данных. Каждый шаг — одна строка, начинается с "
        "короткого действия. В конце — одна ободряющая фраза."
    ),
}

# ── Static template list for the Flutter client ──────────────────────
_TEMPLATES: list[AiTemplateDescriptor] = [
    AiTemplateDescriptor(
        id="headline",
        title="Главное за месяц",
        subtitle="Ключевая картина трёх-четырёх строк",
        icon="auto_awesome",
    ),
    AiTemplateDescriptor(
        id="overshoot",
        title="Где я перебрал?",
        subtitle="Категории, где траты выросли против прошлого месяца",
        icon="trending_up",
    ),
    AiTemplateDescriptor(
        id="cuts",
        title="Что сократить?",
        subtitle="Три мягких конкретных шага",
        icon="content_cut",
    ),
]


def list_templates() -> list[AiTemplateDescriptor]:
    """Static list — no DB lookup needed."""
    return _TEMPLATES


# ── Main entry point ─────────────────────────────────────────────────
async def run_command(command: AiCommand, user: User, db: AsyncSession) -> AiCommandResponse:
    tier = user.subscription.tier if user.subscription else "free"
    daily_limit = PRO_COMMAND_LIMIT if tier == "pro" else FREE_COMMAND_LIMIT

    # 1. Compute input hash from this month's transactions
    month_start = Date.today().replace(day=1)
    month_facts = await _collect_month_facts(user, month_start, db)
    prev_facts = await _collect_month_facts(user, _prev_month_first_day(month_start), db)
    data_hash = _hash_facts(command, month_facts, prev_facts)

    # 2. Cache hit → return immediately, no quota consumed
    cache_row = await _find_cache(user.id, command, data_hash, db)
    if cache_row is not None:
        return AiCommandResponse(
            command=command,
            text=cache_row.response,
            cached=True,
            tokens_used=0,
            used_today=await _used_today(user, db),
            daily_limit=daily_limit,
            generated_at=cache_row.created_at,
        )

    # 3. Cache miss → enforce per-user daily limit
    used_today = await _used_today(user, db, lock=True)
    if used_today >= daily_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Дневной лимит AI-команд исчерпан. "
                "Оформите FinanceAI Plus для трёх инсайтов в день."
                if tier != "pro"
                else "Вы уже использовали все три команды на сегодня."
            ),
        )

    # 4. Soft global budget guard
    await _check_daily_budget(db)

    # 5. Call Claude
    prompt = _build_user_prompt(command, month_facts, prev_facts)
    text, tokens = await _call_anthropic(_PROMPTS[command], prompt)

    # 6. Persist cache + usage atomically (session-level; caller commits)
    now = datetime.now(UTC)
    await _upsert_cache(
        user_id=user.id,
        command=command,
        data_hash=data_hash,
        response=text,
        tokens_used=tokens,
        now=now,
        db=db,
    )
    await _increment_usage(user, db)

    # Also keep a row in ai_messages for audit, without history role structure
    db.add(
        AiMessage(
            user_id=user.id,
            role="assistant",
            content=f"[command:{command}] {text}",
            tokens_used=tokens,
        )
    )

    await db.flush()

    return AiCommandResponse(
        command=command,
        text=text,
        cached=False,
        tokens_used=tokens,
        used_today=used_today + 1,
        daily_limit=daily_limit,
        generated_at=now,
    )


async def get_usage(user: User, db: AsyncSession) -> AiUsageResponse:
    """Light-weight summary for the AI screen header badge."""
    tier = user.subscription.tier if user.subscription else "free"
    daily_limit = PRO_COMMAND_LIMIT if tier == "pro" else FREE_COMMAND_LIMIT

    result = await db.execute(
        select(AiCommandCache).where(AiCommandCache.user_id == user.id)
    )
    by_cmd: dict[str, datetime | None] = {"headline": None, "overshoot": None, "cuts": None}
    for row in result.scalars().all():
        if row.command in by_cmd:
            by_cmd[row.command] = row.created_at

    return AiUsageResponse(
        used_today=await _used_today(user, db),
        daily_limit=daily_limit,
        cached=by_cmd,
    )


# ── Cache helpers ────────────────────────────────────────────────────
async def _find_cache(
    user_id, command: AiCommand, data_hash: str, db: AsyncSession
) -> AiCommandCache | None:
    now = datetime.now(UTC)
    result = await db.execute(
        select(AiCommandCache).where(
            AiCommandCache.user_id == user_id,
            AiCommandCache.command == command,
            AiCommandCache.data_hash == data_hash,
            AiCommandCache.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def _upsert_cache(
    user_id,
    command: AiCommand,
    data_hash: str,
    response: str,
    tokens_used: int,
    now: datetime,
    db: AsyncSession,
) -> None:
    existing = await db.execute(
        select(AiCommandCache).where(
            AiCommandCache.user_id == user_id,
            AiCommandCache.command == command,
        )
    )
    row = existing.scalar_one_or_none()
    expires = now + CACHE_TTL
    if row is None:
        db.add(
            AiCommandCache(
                user_id=user_id,
                command=command,
                data_hash=data_hash,
                response=response,
                tokens_used=tokens_used,
                expires_at=expires,
            )
        )
    else:
        row.data_hash = data_hash
        row.response = response
        row.tokens_used = tokens_used
        row.created_at = now
        row.expires_at = expires


# ── Quota helpers ────────────────────────────────────────────────────
async def _used_today(user: User, db: AsyncSession, lock: bool = False) -> int:
    today = Date.today()
    stmt = select(AiUsage).where(AiUsage.user_id == user.id, AiUsage.date == today)
    if lock:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row.request_count if row else 0


async def _increment_usage(user: User, db: AsyncSession) -> None:
    today = Date.today()
    result = await db.execute(
        select(AiUsage).where(AiUsage.user_id == user.id, AiUsage.date == today)
    )
    row = result.scalar_one_or_none()
    if row:
        row.request_count += 1
    else:
        db.add(AiUsage(user_id=user.id, date=today, request_count=1))


# ── Global budget guard ──────────────────────────────────────────────
async def _check_daily_budget(db: AsyncSession) -> None:
    if settings.ai_daily_budget_usd <= 0:
        return

    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(AiMessage.tokens_used), 0)).where(
            AiMessage.created_at >= since,
        )
    )
    tokens_today = int(result.scalar() or 0)

    # Rough split: assume ratio 70/30 input/output for Haiku
    input_tokens = tokens_today * 0.7
    output_tokens = tokens_today * 0.3
    cost = (
        input_tokens / 1_000_000 * HAIKU_INPUT_COST_PER_1M
        + output_tokens / 1_000_000 * HAIKU_OUTPUT_COST_PER_1M
    )

    if cost >= settings.ai_daily_budget_usd:
        # Fire-and-forget alert. Don't let Telegram failure block the user flow.
        try:
            await notify(
                f"⚠️ AI budget exceeded: ${cost:.2f} of "
                f"${settings.ai_daily_budget_usd:.2f} today"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("telegram notify failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис временно перегружен. Попробуйте завтра.",
        )


# ── Data aggregation ─────────────────────────────────────────────────
def _prev_month_first_day(current_first: Date) -> Date:
    if current_first.month == 1:
        return Date(current_first.year - 1, 12, 1)
    return Date(current_first.year, current_first.month - 1, 1)


async def _collect_month_facts(
    user: User, month_start: Date, db: AsyncSession
) -> dict:
    """Compact snapshot used both for prompt and for cache hashing.

    Returns a dict with totals and top-15 categories — kept small so the
    prompt stays cheap and the hash stable.
    """
    if month_start.month == 12:
        next_month = Date(month_start.year + 1, 1, 1)
    else:
        next_month = Date(month_start.year, month_start.month + 1, 1)

    result = await db.execute(
        select(Transaction, Category)
        .join(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.date >= month_start,
            Transaction.date < next_month,
        )
    )
    rows = result.all()

    income = 0.0
    expense = 0.0
    per_cat: dict[str, dict[str, float]] = defaultdict(
        lambda: {"income": 0.0, "expense": 0.0, "count": 0.0}
    )
    for tx, cat in rows:
        amt = float(tx.amount)
        key = cat.name
        per_cat[key]["count"] += 1
        if tx.type == "income":
            income += amt
            per_cat[key]["income"] += amt
        else:
            expense += amt
            per_cat[key]["expense"] += amt

    # Top 15 spending categories
    top = sorted(
        ((k, v["expense"], int(v["count"])) for k, v in per_cat.items()),
        key=lambda x: x[1],
        reverse=True,
    )[:15]

    return {
        "month": month_start.isoformat(),
        "income": round(income, 2),
        "expense": round(expense, 2),
        "balance": round(income - expense, 2),
        "tx_count": len(rows),
        "top": [
            {"name": name, "expense": round(exp, 2), "count": cnt}
            for name, exp, cnt in top
        ],
    }


def _hash_facts(command: AiCommand, current: dict, previous: dict) -> str:
    payload = json.dumps(
        {"c": command, "cur": current, "prev": previous},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()  # noqa: S324 — not security


def _build_user_prompt(command: AiCommand, current: dict, previous: dict) -> str:
    """Compact, text-format payload for Claude — ~200 tokens max."""
    lines = [
        f"Текущий месяц ({current['month']}):",
        f"  доходы {current['income']}, расходы {current['expense']}, баланс {current['balance']}",
        f"  транзакций {current['tx_count']}",
        "  топ категорий расходов:",
    ]
    for c in current["top"]:
        lines.append(f"    — {c['name']}: {c['expense']} ({c['count']} операций)")

    if previous["tx_count"] > 0:
        lines.append("")
        lines.append(f"Прошлый месяц ({previous['month']}):")
        lines.append(
            f"  расходы {previous['expense']}, "
            f"транзакций {previous['tx_count']}"
        )
        if previous["top"]:
            lines.append("  топ категорий расходов:")
            for c in previous["top"]:
                lines.append(f"    — {c['name']}: {c['expense']}")

    if command == "overshoot":
        lines.append("")
        lines.append("Задача: покажи, где траты заметно выросли по сравнению с прошлым месяцем.")
    elif command == "cuts":
        lines.append("")
        lines.append("Задача: предложи три конкретных способа сократить расходы.")
    else:
        lines.append("")
        lines.append("Задача: сформулируй короткое наблюдение о текущем месяце.")
    return "\n".join(lines)


# ── Anthropic call ───────────────────────────────────────────────────
async def _call_anthropic(system_prompt: str, user_prompt: str) -> tuple[str, int]:
    if not settings.anthropic_api_key:
        return (
            "AI-советник пока не настроен: не задан ANTHROPIC_API_KEY.",
            0,
        )

    import anthropic

    client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.RateLimitError:
        return "Советник перегружен, попробуйте через минуту.", 0
    except anthropic.APIStatusError as e:
        logger.warning("anthropic api error: %s", e)
        return "Советник временно недоступен. Попробуйте позже.", 0
    except Exception as e:  # noqa: BLE001
        logger.warning("anthropic unexpected error: %s", e)
        return "Не удалось получить ответ. Попробуйте позже.", 0

    content = response.content[0].text if response.content else ""
    tokens_used = response.usage.input_tokens + response.usage.output_tokens
    return content, tokens_used
