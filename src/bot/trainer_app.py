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

from src.bot import trainer_benchmark_config as bench_cfg
from src.bot.schedule_notifications import set_client_bot
from src.bot.handlers.trainer_handlers import router as trainer_router
from src.bot.middlewares.trainer_benchmark_middleware import TrainerBenchmarkMiddleware
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.bot.middlewares.service_unavailable_middleware import ServiceUnavailableMiddleware
from src.bot.middlewares.trainer_gate_middleware import TrainerGateMiddleware
from src.bot.middlewares.trainer_menu_sync_middleware import TrainerMenuSyncMiddleware
from src.bot.trainer_menu_commands import (
    restore_all_linked_trainer_hub_menu_buttons,
    set_default_trainer_commands_without_stats,
)
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base
from src.shared.sentry_init import init_sentry
from src.shared.rate_limit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def setup_menu_and_commands(bot: Bot) -> None:
    """Default scope: no slash menu; linked chats get per-chat «Обзор» via TrainerMenuSyncMiddleware."""
    await set_default_trainer_commands_without_stats(bot)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    _base, src = mini_app_https_base(Settings())
    logger.info(
        "Trainer bot: default menu = empty slash list [%s]; "
        "linked chats get «Обзор» Web App button only",
        src,
    )


async def main() -> None:
    settings = Settings()
    init_sentry(settings, "bot-trainer")
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
    asyncio.create_task(restore_all_linked_trainer_hub_menu_buttons(bot))
    bench_cfg.configure(
        log_every_update=settings.trainer_bot_benchmark_log,
        slow_total_ms=settings.trainer_bot_benchmark_slow_ms,
    )
    if bench_cfg.is_active():
        logger.info(
            "Trainer bot benchmark: log_every=%s slow_ms=%s — "
            "lines BENCH trainer_* come from logger trainer_bot.bench on each Telegram update "
            "(message/callback/etc.). Mini App opens /api/webapp/* on the API process; "
            "that uses trainer_webapp.bench if TRAINER_WEBAPP_BENCHMARK_LOG is set there, not here.",
            settings.trainer_bot_benchmark_log,
            settings.trainer_bot_benchmark_slow_ms,
        )
    dp = Dispatcher(storage=MemoryStorage())
    limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_sec=settings.rate_limit_window_sec,
    )
    dp.update.outer_middleware(RateLimitMiddleware(limiter, bot))
    dp.update.outer_middleware(TrainerBenchmarkMiddleware())
    # Menu sync before gate: always re-apply «Обзор» for linked trainers even when gate blocks.
    menu_sync = TrainerMenuSyncMiddleware()
    dp.message.outer_middleware(menu_sync)
    dp.callback_query.outer_middleware(menu_sync)
    # Gate on Dispatcher outer_middleware — wraps entire router tree so allowlist runs before handlers.
    trainer_gate = TrainerGateMiddleware()
    dp.message.outer_middleware(trainer_gate)
    dp.callback_query.outer_middleware(trainer_gate)
    dp.include_router(trainer_router)
    # Outermost catch: DB down / MAINTENANCE_MODE → user-facing «технические работы».
    dp.update.outer_middleware(ServiceUnavailableMiddleware())
    logger.info("Trainer bot polling started (notifications run in notification_service)")
    try:
        await dp.start_polling(bot)
    finally:
        set_client_bot(None)
        await client_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
