"""
Trainer bot entry point. Entry only via paid link from site (t.me/bot?start=link_<token>).
Run: python -m src.bot.trainer_app
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.shared.config import Settings
from src.bot.handlers.trainer_handlers import router as trainer_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(trainer_router)
    logger.info("Trainer bot polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
