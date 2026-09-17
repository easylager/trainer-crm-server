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

from src.shared.config import Settings
from src.shared.sentry_init import init_sentry
from src.bot.client_menu_commands import sync_client_hub_menu_button
from src.bot.handlers.client_handlers import router as client_router
from src.bot.middlewares.client_menu_sync_middleware import ClientMenuSyncMiddleware
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.bot.middlewares.service_unavailable_middleware import ServiceUnavailableMiddleware
from src.shared.rate_limit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def setup_menu_and_commands(bot: Bot) -> None:
    """Hub-only UX: no command list in the menu; single tap opens client-home Mini App (HTTPS).

    Without HTTPS the Web App menu button is unavailable — menu falls back to empty commands.
    Sets the bot-wide default; ClientMenuSyncMiddleware re-applies it per-chat afterwards
    since Telegram silently drops it for individual chats after Mini App use.
    """
    await bot.set_my_commands([])
    await sync_client_hub_menu_button(bot)
    logger.info("Client bot: menu configured")


async def main() -> None:
    settings = Settings()
    init_sentry(settings, "bot-client")
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
    dp.update.outer_middleware(ServiceUnavailableMiddleware())
    dp.update.outer_middleware(ClientMenuSyncMiddleware())
    dp.include_router(client_router)
    logger.info("Client bot polling started (notifications run in notification_service)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
