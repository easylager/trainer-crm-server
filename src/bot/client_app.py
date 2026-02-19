"""
Client bot entry point. Public: anyone can /start and use as client.
Run: python -m src.bot.client_app
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.shared.config import Settings
from src.bot.handlers.client_handlers import router as client_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(client_router)
    logger.info("Client bot polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
