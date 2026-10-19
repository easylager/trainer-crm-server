"""Напоминания и правка карточек компании. Один процесс notification_service."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from src.application.ice_company.delivery import AiogramSender
from src.application.ice_company.lifecycle import tick
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def run_ice_company_loop(bot: Bot, *, interval_sec: float = 20) -> None:
    settings = Settings()
    sender = AiogramSender(bot, settings)
    while True:
        try:
            async with async_session_factory() as session:
                stats = await tick(session, sender, settings=settings)
            if any(stats.values()):
                logger.info("ice_company tick %s", stats)
        except Exception:
            logger.exception("ice_company tick failed")
        await asyncio.sleep(interval_sec)
