"""
Entry point for Telegram bot.
Run: python -m src.bot.main
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# TODO: load from pydantic-settings
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    # TODO: get token from settings
    token = "YOUR_BOT_TOKEN"  # replace with os.getenv / Settings
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    @dp.message()
    async def echo_handler(message):
        await message.answer(f"Echo: {message.text}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
