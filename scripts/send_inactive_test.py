"""
Send test "inactive client" (10 / 30 days) messages to NOTIFY_TELEGRAM_ID via client bot.
No DB, no loops — just one-time push to check copy and button.

Usage:
  python -m scripts.send_inactive_test

Env:
  .env: telegram_bot_token_client, NOTIFY_TELEGRAM_ID (your Telegram user id)
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import messages as msg
from src.shared.config import Settings


async def main() -> None:
    settings = Settings()
    chat_id = settings.notify_telegram_id
    if chat_id is None:
        print("Set NOTIFY_TELEGRAM_ID in .env (your Telegram user id) and run again.")
        sys.exit(1)

    bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_BUTTON_BOOK, callback_data="catalog")],
    ])

    text_10 = msg.CLIENT_INACTIVE_10_DAYS.format(name="")  # or ", Вася" to test with name
    await bot.send_message(chat_id=chat_id, text=text_10, reply_markup=kb)
    print("Sent 10-day message.")

    text_30 = msg.CLIENT_INACTIVE_30_DAYS.format(name="")
    await bot.send_message(chat_id=chat_id, text=text_30, reply_markup=kb)
    print("Sent 30-day message.")

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
