import uuid
from datetime import UTC, datetime, date as Date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.telegram import fmt_ai_dialog, fmt_ai_limit, notify
from app.models.ai import AiMessage, AiPromptTemplate, AiUsage
from app.models.transaction import Transaction, Category
from app.models.user import User
from app.schemas.ai import AiAskRequest, AiChatResponse, AiMessageResponse, AiPromptTemplateResponse

FREE_DAILY_LIMIT = 5


async def get_templates(db: AsyncSession) -> list[AiPromptTemplateResponse]:
    result = await db.execute(
        select(AiPromptTemplate)
        .where(AiPromptTemplate.is_active == True)
        .order_by(AiPromptTemplate.sort_order)
    )
    return [AiPromptTemplateResponse.model_validate(t) for t in result.scalars().all()]


async def get_chat(user: User, db: AsyncSession) -> AiChatResponse:
    # Берём последние 100 сообщений (DESC), затем разворачиваем для хронологии
    result = await db.execute(
        select(AiMessage)
        .where(AiMessage.user_id == user.id, AiMessage.cleared_at.is_(None))
        .order_by(AiMessage.created_at.desc())
        .limit(100)
    )
    messages = list(reversed(result.scalars().all()))

    requests_today, daily_limit = await _get_usage_info(user, db)

    return AiChatResponse(
        messages=[AiMessageResponse.model_validate(m) for m in messages],
        requests_today=requests_today,
        daily_limit=daily_limit,
    )


async def ask(data: AiAskRequest, user: User, db: AsyncSession) -> AiMessageResponse:
    tier = user.subscription.tier if user.subscription else "free"

    if tier != "pro":
        # SELECT FOR UPDATE: блокирует строку — конкурентные запросы того же юзера ждут.
        # Это предотвращает race condition когда 2 запроса одновременно проходят проверку.
        today = Date.today()
        usage_result = await db.execute(
            select(AiUsage)
            .where(AiUsage.user_id == user.id, AiUsage.date == today)
            .with_for_update()
        )
        usage_row = usage_result.scalar_one_or_none()
        requests_today = usage_row.request_count if usage_row else 0

        if requests_today >= FREE_DAILY_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Daily limit of {FREE_DAILY_LIMIT} AI requests reached. Upgrade to Pro for unlimited access.",
            )

    # Валидируем prompt_template_id если передан
    if data.prompt_template_id is not None:
        template = await db.get(AiPromptTemplate, data.prompt_template_id)
        if not template or not template.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found")

    # Сохраняем сообщение пользователя
    user_msg = AiMessage(
        user_id=user.id,
        role="user",
        content=data.message,
        prompt_template_id=data.prompt_template_id,
    )
    db.add(user_msg)
    await db.flush()

    # Получаем историю для контекста (последние 10 сообщений)
    history_result = await db.execute(
        select(AiMessage)
        .where(AiMessage.user_id == user.id, AiMessage.cleared_at.is_(None))
        .order_by(AiMessage.created_at.desc())
        .limit(10)
    )
    history = list(reversed(history_result.scalars().all()))

    # Получаем последние транзакции для контекста
    tx_context = await _build_transaction_context(user, db)

    # Вызываем Anthropic
    assistant_content, tokens_used = await _call_anthropic(data.message, history[:-1], tx_context)

    # Сохраняем ответ ассистента
    assistant_msg = AiMessage(
        user_id=user.id,
        role="assistant",
        content=assistant_content,
        tokens_used=tokens_used,
    )
    db.add(assistant_msg)

    # Обновляем счётчик использования
    await _increment_usage(user, db)

    await db.flush()

    # Логируем диалог и лимиты в Telegram
    await notify(fmt_ai_dialog(user.email, data.message, assistant_content, tokens_used))
    if tier != "pro":
        new_count, _ = await _get_usage_info(user, db)
        if new_count >= FREE_DAILY_LIMIT:
            await notify(fmt_ai_limit(user.email, new_count, FREE_DAILY_LIMIT))
        elif new_count == FREE_DAILY_LIMIT - 1:
            await notify(fmt_ai_limit(user.email, new_count, FREE_DAILY_LIMIT))

    return AiMessageResponse.model_validate(assistant_msg)


async def delete_message(message_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    result = await db.execute(
        select(AiMessage).where(
            AiMessage.id == message_id,
            AiMessage.user_id == user.id,
            AiMessage.cleared_at.is_(None),
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    msg.cleared_at = datetime.now(UTC)


async def clear_chat(user: User, db: AsyncSession) -> None:
    result = await db.execute(
        select(AiMessage)
        .where(AiMessage.user_id == user.id, AiMessage.cleared_at.is_(None))
    )
    now = datetime.now(UTC)
    for msg in result.scalars().all():
        msg.cleared_at = now


async def _get_usage_info(user: User, db: AsyncSession) -> tuple[int, int]:
    tier = user.subscription.tier if user.subscription else "free"
    today = Date.today()

    result = await db.execute(
        select(AiUsage).where(AiUsage.user_id == user.id, AiUsage.date == today)
    )
    usage = result.scalar_one_or_none()
    requests_today = usage.request_count if usage else 0
    daily_limit = -1 if tier == "pro" else FREE_DAILY_LIMIT

    return requests_today, daily_limit


async def _increment_usage(user: User, db: AsyncSession) -> None:
    today = Date.today()
    result = await db.execute(
        select(AiUsage).where(AiUsage.user_id == user.id, AiUsage.date == today)
    )
    usage = result.scalar_one_or_none()
    if usage:
        usage.request_count += 1
    else:
        db.add(AiUsage(user_id=user.id, date=today, request_count=1))


async def _build_transaction_context(user: User, db: AsyncSession) -> str:
    from datetime import timedelta
    since = Date.today() - timedelta(days=30)

    result = await db.execute(
        select(Transaction, Category)
        .join(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.date >= since,
        )
        .order_by(Transaction.date.desc())
        .limit(150)
    )
    rows = result.all()

    if not rows:
        return "У пользователя нет транзакций за последние 30 дней."

    total_income = sum(tx.amount for tx, _ in rows if tx.type == "income")
    total_expense = sum(tx.amount for tx, _ in rows if tx.type == "expense")
    balance = total_income - total_expense

    lines = [
        f"Период: последние 30 дней ({since} — {Date.today()})",
        f"Доходы: {total_income} | Расходы: {total_expense} | Баланс: {'+' if balance >= 0 else ''}{balance}",
        "",
        "Все транзакции:",
    ]
    for tx, cat in rows:
        lines.append(f"- {tx.date}: {tx.type} {tx.amount} ({cat.name}){' — ' + tx.note if tx.note else ''}")

    return "\n".join(lines)


async def _call_anthropic(user_message: str, history: list[AiMessage], tx_context: str) -> tuple[str, int]:
    if not settings.anthropic_api_key:
        # Режим без ключа — заглушка для тестирования
        return (
            "AI советник недоступен: не задан ANTHROPIC_API_KEY в .env. "
            "Добавь ключ и перезапусти сервер.",
            0,
        )

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    system_prompt = f"""Ты — персональный финансовый советник в мобильном приложении FinanceAI.
Твоя задача — анализировать расходы пользователя и давать конкретные, практичные советы.
Отвечай коротко и по делу (2-4 абзаца максимум). Используй простой язык.

{tx_context}"""

    messages = []
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
    except anthropic.RateLimitError:
        return "Советник перегружен, попробуй через минуту.", 0
    except anthropic.APIStatusError:
        return "Советник временно недоступен. Попробуй позже.", 0
    except Exception:
        return "Не удалось получить ответ. Попробуй позже.", 0

    content = response.content[0].text
    tokens_used = response.usage.input_tokens + response.usage.output_tokens

    return content, tokens_used
