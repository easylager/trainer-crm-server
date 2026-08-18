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
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from src.bot import messages as msg
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base
from src.shared.sentry_init import init_sentry
from src.bot.handlers.client_handlers import router as client_router
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.bot.middlewares.service_unavailable_middleware import ServiceUnavailableMiddleware
from src.shared.rate_limit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def setup_menu_and_commands(bot: Bot) -> None:
    """Hub-only UX: no command list in the menu; single tap opens client-home Mini App (HTTPS).

    Without HTTPS the Web App menu button is unavailable — menu falls back to empty commands.
    """
    settings = Settings()
    await bot.set_my_commands([])
    base, src = mini_app_https_base(settings)
    if base:
        hub_url = f"{base}/webapp/client-home"
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text=msg.CLIENT_MENU_BUTTON_HUB,
                web_app=WebAppInfo(url=hub_url),
            ),
        )
        logger.info("Client bot: menu button = Web App hub only, commands cleared (%s) [%s]", hub_url, src)
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info(
            "Client bot: no HTTPS — menu button = commands (empty); set WEBAPP_BASE_URL or API_BASE_URL to https:// for hub button [%s]",
            src,
        )
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
    dp.include_router(client_router)
    logger.info("Client bot polling started (notifications run in notification_service)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
