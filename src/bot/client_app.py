"""
Client bot entry point. Public: anyone can /start and use as client.
Run: python -m src.bot.client_app

Notification loops (reminders, complete/cancel/response/trainer_booked/inactive) run in a separate
process: python -m src.bot.notification_service
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonCommands

from src.shared.config import Settings
from src.bot.handlers.client_handlers import router as client_router
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.shared.rate_limit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def setup_menu_and_commands(bot: Bot) -> None:
    """Menu button (left of attachment): opens command list. /start is intentionally hidden."""
    await bot.set_my_commands(
        [
            BotCommand(command="guide", description="Помощь"),
            BotCommand(command="settings", description="Тренеры и запись"),
            BotCommand(command="my_requests", description="Мои заявки и отклики"),
            BotCommand(command="my_bookings", description="Мои записи"),
            BotCommand(command="my_passes", description="Мои абонементы"),
            BotCommand(command="my_certificates", description="Мои сертификаты"),
        ]
    )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Menu button and commands set")


async def main() -> None:
    settings = Settings()
    bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await setup_menu_and_commands(bot)
    dp = Dispatcher()
    limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_sec=settings.rate_limit_window_sec,
    )
    dp.update.outer_middleware(RateLimitMiddleware(limiter, bot))
    dp.include_router(client_router)
    logger.info("Client bot polling started (notifications run in notification_service)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
