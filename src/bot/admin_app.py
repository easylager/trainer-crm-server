"""
Admin bot entry point. Used for manual moderation of trainers.
Run: python -m src.bot.admin_app
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonCommands

from src.bot.handlers.admin_handlers import router as admin_router
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.shared.config import Settings
from src.shared.rate_limit import RateLimiter


logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def setup_menu_and_commands(bot: Bot) -> None:
    """Menu button: show admin commands."""
    await bot.set_my_commands(
        [
            BotCommand(command="pending", description="Тренеры на модерацию"),
            BotCommand(command="stats", description="Статистика платформы"),
        ]
    )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Admin bot: menu button and commands set")


async def main() -> None:
    settings = Settings()
    if not settings.telegram_bot_token_admin:
        raise RuntimeError("telegram_bot_token_admin is not set in settings/.env")
    bot = Bot(
        token=settings.telegram_bot_token_admin,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await setup_menu_and_commands(bot)
    dp = Dispatcher()
    limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_sec=settings.rate_limit_window_sec,
    )
    dp.update.outer_middleware(RateLimitMiddleware(limiter, bot))
    dp.include_router(admin_router)
    logger.info("Admin bot polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

