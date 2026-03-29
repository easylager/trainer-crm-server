"""
Trainer bot entry point. Entry only via paid link from site (t.me/bot?start=link_<token>).
Run: python -m src.bot.trainer_app

Notification loops (booking/request/completed/daily reminders) run in a separate process:
python -m src.bot.notification_service
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonCommands

from src.bot.schedule_notifications import set_client_bot
from src.bot.handlers.trainer_handlers import router as trainer_router
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.bot.middlewares.trainer_gate_middleware import TrainerGateMiddleware
from src.bot.middlewares.trainer_menu_sync_middleware import TrainerMenuSyncMiddleware
from src.bot.trainer_menu_commands import set_default_trainer_commands_without_stats
from src.shared.config import Settings
from src.shared.rate_limit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def setup_menu_and_commands(bot: Bot) -> None:
    """Default command list (minimal); per-chat list set when trainer is active (CRM + Analytics add commands)."""
    await set_default_trainer_commands_without_stats(bot)
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
    dp = Dispatcher(storage=MemoryStorage())
    limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_sec=settings.rate_limit_window_sec,
    )
    dp.update.outer_middleware(RateLimitMiddleware(limiter, bot))
    trainer_router.message.middleware(TrainerGateMiddleware())
    trainer_router.message.middleware(TrainerMenuSyncMiddleware())
    trainer_router.callback_query.middleware(TrainerGateMiddleware())
    trainer_router.callback_query.middleware(TrainerMenuSyncMiddleware())
    dp.include_router(trainer_router)
    logger.info("Trainer bot polling started (notifications run in notification_service)")
    try:
        await dp.start_polling(bot)
    finally:
        set_client_bot(None)
        await client_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
