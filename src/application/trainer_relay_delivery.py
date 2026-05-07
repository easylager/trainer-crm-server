"""Send relay messages through Telegram bots (trainer↔client, two-bot setup)."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot import messages as msg
from src.bot.trainer_bot_state import clear_trainer_relay_reply_pending
from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def send_client_relay_from_trainer(
    *,
    client_telegram_id: int,
    trainer_display_name: str,
    body_text: str,
    session_id: int,
) -> None:
    """Private chat → **client** bot DM (inline «Ответить» — same pattern as trainer side)."""
    settings = Settings()
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        text_html = msg.format_client_relay_from_trainer_html(
            trainer_name=trainer_display_name,
            body_text=body_text,
        )
        kb = msg.build_client_relay_reply_only_keyboard(session_id)
        await client_bot.send_message(
            chat_id=int(client_telegram_id),
            text=text_html,
            reply_markup=kb,
        )
    finally:
        await client_bot.session.close()


async def send_trainer_relay_from_client(
    *,
    trainer_telegram_id: int,
    client_display_name: str,
    body_text: str,
    session_id: int,
) -> None:
    """Private chat → **trainer** bot DM (inline «Ответить» only — no manual «close»)."""
    settings = Settings()
    trainer_bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        text_html = msg.format_trainer_relay_from_client_html(
            client_name=client_display_name,
            body_text=body_text,
        )
        kb = msg.build_trainer_relay_reply_only_keyboard(session_id)
        await trainer_bot.send_message(
            chat_id=int(trainer_telegram_id),
            text=text_html,
            reply_markup=kb,
        )
    finally:
        await trainer_bot.session.close()


async def send_trainer_plain_notification(*, telegram_chat_id: int, html_text: str) -> None:
    """Trainer bot message without keyboards (hints after close)."""
    settings = Settings()
    trainer_bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await trainer_bot.send_message(chat_id=int(telegram_chat_id), text=html_text)
    finally:
        await trainer_bot.session.close()


async def send_client_plain_notification(*, telegram_chat_id: int, html_text: str) -> None:
    """Client bot DM without keyboards."""
    settings = Settings()
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await client_bot.send_message(chat_id=int(telegram_chat_id), text=html_text)
    finally:
        await client_bot.session.close()


async def notify_relay_sessions_closed_idle(rows: list[dict[str, Any]]) -> None:
    """
    Fire-and-forget Telegram hints after idle TTL closed sessions.
    Dedupes Telegram hints per trainer and per client when many sessions expire at once.
    """
    if not rows:
        return
    seen_client: set[int] = set()
    seen_trainer: set[int] = set()
    hint = msg.RELAY_SESSION_IDLE_CLOSED_HINT
    for row in rows:
        ttg = row.get("trainer_telegram_id")
        if ttg is not None:
            tt = int(ttg)
            clear_trainer_relay_reply_pending(tt)
            if tt not in seen_trainer:
                seen_trainer.add(tt)
                try:
                    await send_trainer_plain_notification(telegram_chat_id=tt, html_text=hint)
                except Exception:
                    logger.exception("relay_idle_notify_trainer_failed tg=%s", ttg)
        ctg = row.get("client_telegram_id")
        if ctg is None:
            continue
        cid = int(ctg)
        if cid in seen_client:
            continue
        seen_client.add(cid)
        try:
            await send_client_plain_notification(telegram_chat_id=cid, html_text=hint)
        except Exception:
            logger.exception("relay_idle_notify_client_failed tg=%s", ctg)


async def sweep_idle_relay_sessions_and_notify() -> None:
    """Own transaction: close stale open sessions, then Telegram hints (deduped per trainer and per client)."""
    from src.application.trainer_client_relay_use_cases import close_idle_open_relay_sessions
    from src.infrastructure.db import async_session_factory

    async with async_session_factory() as session:
        closed = await close_idle_open_relay_sessions(session)
        if not closed:
            return
        await session.commit()
    await notify_relay_sessions_closed_idle(closed)
