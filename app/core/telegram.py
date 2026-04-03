import asyncio

import httpx

from app.core.config import settings


async def _send(text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                json={"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
    except Exception:
        pass  # Telegram недоступен — не роняем приложение


async def notify(text: str) -> None:
    """Fire-and-forget: не блокирует ответ пользователю."""
    asyncio.create_task(_send(text))


# ── Форматтеры событий ────────────────────────────────────────────

def fmt_register(email: str, name: str) -> str:
    return f"🆕 <b>Новый пользователь</b>\n👤 {name}\n📧 {email}"


def fmt_login(email: str, tier: str) -> str:
    tier_label = "💎 Pro" if tier == "pro" else "🆓 Free"
    return f"🔑 <b>Вход в приложение</b>\n📧 {email}\n{tier_label}"


def fmt_first_transaction(email: str, amount, tx_type: str, category: str) -> str:
    emoji = "💸" if tx_type == "expense" else "💰"
    return f"✅ <b>Первая транзакция</b>\n📧 {email}\n{emoji} {amount} ({category}) — {tx_type}"


def fmt_first_category(email: str, name: str) -> str:
    return f"📂 <b>Первая своя категория</b>\n📧 {email}\n🏷 {name}"


def fmt_ai_dialog(email: str, question: str, tokens: int) -> str:
    q = question[:300] + "…" if len(question) > 300 else question
    return (
        f"🤖 <b>AI запрос</b>\n"
        f"📧 {email}\n"
        f"❓ <i>{q}</i>\n"
        f"🔢 Токены: {tokens}"
    )


def fmt_ai_limit(email: str, count: int, limit: int) -> str:
    if count >= limit:
        return f"🚫 <b>AI лимит исчерпан</b>\n📧 {email}\n📊 {count}/{limit} запросов сегодня"
    return f"🔔 <b>AI лимит скоро кончится</b>\n📧 {email}\n📊 {count}/{limit} запросов использовано"


def fmt_http_error(status_code: int, method: str, path: str) -> str:
    if status_code >= 500:
        return f"🔴 <b>Ошибка {status_code}</b>\n🛣 {method} {path}"
    return f"⚠️ <b>{status_code}</b> {method} {path}"
