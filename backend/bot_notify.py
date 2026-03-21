"""
Notification helpers — called by scheduled tasks.
The main bot runs separately; this module only sends push messages.
"""
from telegram import Bot
from backend.config import BOT_TOKEN
import backend.database as db


async def send_recurring_reminder(user_id: int, items: list[dict]) -> None:
    if not BOT_TOKEN or not items:
        return
    bot = Bot(token=BOT_TOKEN)
    lines = ["📅 Напоминание о регулярных транзакциях на сегодня:\n"]
    for item in items:
        lines.append(f"  {item['category_emoji']} {item['category_name']} — {item['amount']:,.0f} L".replace(",", " "))
    await bot.send_message(chat_id=user_id, text="\n".join(lines))


async def send_limit_warning(user_id: int, category_name: str, emoji: str, percent: float) -> None:
    if not BOT_TOKEN:
        return
    bot = Bot(token=BOT_TOKEN)
    icon = "🚨" if percent >= 100 else "⚠️"
    msg = f"{icon} Лимит по категории {emoji} {category_name}: использовано {percent:.0f}%"
    await bot.send_message(chat_id=user_id, text=msg)


async def notify_recurring_today() -> None:
    """Send reminders for recurring transactions due today. Call at 09:00 UTC."""
    conn = await db.get_db()
    try:
        async with conn.execute(
            """SELECT DISTINCT r.user_id FROM recurring_transactions r
               WHERE r.day_of_month = CAST(strftime('%d', 'now') AS INTEGER)"""
        ) as cur:
            user_ids = [row[0] for row in await cur.fetchall()]

        for uid in user_ids:
            items = await db.get_recurring(conn, uid)
            today_items = [
                i for i in items
                if i["day_of_month"] == int(__import__("datetime").date.today().strftime("%d"))
            ]
            await send_recurring_reminder(uid, today_items)
    finally:
        await conn.close()
