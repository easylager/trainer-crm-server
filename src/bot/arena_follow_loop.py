"""Петля доставки «следить за катком». Ретрай как у booking-confirm: строка остаётся, пока не уйдёт."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from src.application.arena_follow_notify import FollowBotBlocked, FollowOutbound, dispatch_due_follow_notifications
from src.bot.arena_follow_keyboards import follow_reply_markup
from src.infrastructure.db.session import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)

ARENA_FOLLOW_NOTIFIER_INTERVAL_SEC = 30

_BLOCKED_MARKERS = (
    "bot was blocked",
    "user is deactivated",
    "chat not found",
    "bot can't initiate",
    "have no rights",
)


def _is_blocked_message(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _BLOCKED_MARKERS)


async def _send(bot: Bot, item: FollowOutbound) -> None:
    markup = follow_reply_markup(item.buttons)

    async def _once() -> None:
        await bot.send_message(chat_id=item.telegram_id, text=item.text, reply_markup=markup)

    try:
        await _once()
    except TelegramRetryAfter as exc:
        delay = float(exc.retry_after or 1)
        if delay > 30:
            raise
        await asyncio.sleep(delay + 0.5)
        await _once()
    except TelegramForbiddenError as exc:
        raise FollowBotBlocked(str(exc)) from exc
    except TelegramBadRequest as exc:
        if _is_blocked_message(exc):
            raise FollowBotBlocked(str(exc)) from exc
        raise


async def run_arena_follow_notifier_loop(client_bot: Bot) -> None:
    logger.info("[arena_follow_loop] started")
    while True:
        try:
            await asyncio.sleep(ARENA_FOLLOW_NOTIFIER_INTERVAL_SEC)
            settings = Settings()

            async def _deliver(item: FollowOutbound) -> None:
                await _send(client_bot, item)

            async with async_session_factory() as session:
                await dispatch_due_follow_notifications(
                    session,
                    now=datetime.now(timezone.utc),
                    webapp_base_url=settings.webapp_base_url or "",
                    send=_deliver,
                )
        except asyncio.CancelledError:
            logger.info("[arena_follow_loop] cancelled")
            break
        except Exception:
            logger.exception("arena follow notifier")
