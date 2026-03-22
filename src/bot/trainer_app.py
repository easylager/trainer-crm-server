"""
Trainer bot entry point. Entry only via paid link from site (t.me/bot?start=link_<token>).
Run: python -m src.bot.trainer_app

Notification loops (booking/request/completed/daily reminders) run in a separate process:
python -m src.bot.notification_service
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonCommands

from src.bot.schedule_notifications import set_client_bot
from src.bot.handlers.trainer_handlers import router as trainer_router
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.shared.config import Settings
from src.shared.rate_limit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def setup_menu_and_commands(bot: Bot) -> None:
    """Commands list + menu button: use default commands menu (full list)."""
    await bot.set_my_commands(
        [
            BotCommand(command="guide", description="Помощь"),
            BotCommand(command="editor", description="Расписание"),
            BotCommand(command="requests", description="Заявки клиентов"),
            BotCommand(command="clients", description="Мои клиенты"),
            BotCommand(command="bookings", description="Мои записи"),
            BotCommand(command="passes", description="Абонементы/Сертификаты"),
            BotCommand(command="subscription", description="Подписка"),
            BotCommand(command="stats", description="Статистика"),
        ]
    )
    # Default menu: full list of commands in Telegram menu (left of input)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Trainer bot: menu button and commands set")


async def main() -> None:
    settings = Settings()
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    set_client_bot(client_bot)
    await setup_menu_and_commands(bot)
    dp = Dispatcher()
    limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_sec=settings.rate_limit_window_sec,
    )
    dp.update.outer_middleware(RateLimitMiddleware(limiter, bot))
    dp.include_router(trainer_router)
    logger.info("Trainer bot polling started (notifications run in notification_service)")
    try:
        await dp.start_polling(bot)
    finally:
        set_client_bot(None)
        await client_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
