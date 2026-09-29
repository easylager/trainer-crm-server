"""
Org bot entry point (TASK-141/EPIC5 TASK-105) — school director/operator bot, separate process
from the trainer and client bots. Entry only via col_claim_* deep link.

Run: python -m src.bot.org_app
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from src.bot import messages as msg
from src.bot.handlers.org_handlers import org_cabinet_webapp_url, router as org_router
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.bot.middlewares.service_unavailable_middleware import ServiceUnavailableMiddleware
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base
from src.shared.sentry_init import init_sentry
from src.shared.rate_limit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def setup_org_menu(bot: Bot) -> None:
    """Menu button opens the org cabinet. Telegram requires HTTPS."""
    settings = Settings()
    await bot.set_my_commands([])
    https, src = mini_app_https_base(settings)
    url = org_cabinet_webapp_url() if https else None
    if url and url.lower().startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text=msg.ORG_BTN_OPEN_CABINET,
                web_app=WebAppInfo(url=url),
            ),
        )
        logger.info("Org bot: menu button = Web App (%s) [%s]", url, src)
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Org bot: no HTTPS Mini App base — menu = commands [%s]", src)


async def main() -> None:
    settings = Settings()
    init_sentry(settings, "bot-org")
    token = settings.telegram_bot_token_org
    if not token:
        logger.error("Org bot: TELEGRAM_BOT_TOKEN_ORG not set — nothing to run.")
        return
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_sec=settings.rate_limit_window_sec,
    )
    dp.update.outer_middleware(RateLimitMiddleware(limiter, bot))
    dp.include_router(org_router)
    # Outermost catch: DB down / MAINTENANCE_MODE → user-facing «технические работы».
    dp.update.outer_middleware(ServiceUnavailableMiddleware())
    await setup_org_menu(bot)
    logger.info("Org bot polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
