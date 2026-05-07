"""Bot-side routing for trainer↔client relay (dual-bot orchestration)."""

from __future__ import annotations

import logging

from aiogram.types import CallbackQuery, Message

from src.application.trainer_client_relay_use_cases import (
    RELAY_SENDER_CLIENT,
    RELAY_SENDER_TRAINER,
    close_relay_session,
    insert_relay_message,
    relay_open_session_context_for_client_telegram,
    relay_session_context_for_id,
    sanitize_relay_body,
    trainer_public_display_name,
)
from src.application.trainer_relay_delivery import (
    send_client_plain_notification,
    send_client_relay_from_trainer,
    send_trainer_plain_notification,
    send_trainer_relay_from_client,
    sweep_idle_relay_sessions_and_notify,
)
from src.bot import messages as msg
from src.bot.trainer_bot_state import (
    set_trainer_relay_reply_pending,
    trainer_booking_note_awaiting,
    trainer_support_awaiting,
)
from src.infrastructure.db import async_session_factory

logger = logging.getLogger(__name__)


def _relay_callback_session_id(callback_data: str | None, prefix: str) -> int | None:
    raw = callback_data or ""
    if not raw.startswith(prefix):
        return None
    try:
        return int(raw.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


async def maybe_route_client_relay_text_reply(message: Message) -> bool:
    """
    If this private text belongs to an open relay session — forward to trainer and return True.
    """
    uid = message.from_user.id if message.from_user else 0
    if not uid:
        return False
    if message.chat.type != "private":
        return False
    raw = sanitize_relay_body(message.text or "")
    if raw is None:
        return False
    await sweep_idle_relay_sessions_and_notify()
    async with async_session_factory() as session:
        ctx = await relay_open_session_context_for_client_telegram(session, client_telegram_id=int(uid))
        if not ctx:
            return False
        sid = int(ctx["session_id"])
        trainer_tg = ctx.get("trainer_telegram_id")
        trainer_id = int(ctx["trainer_id"])
        client_row = await relay_session_context_for_id(session, session_id=sid)
        if not client_row or client_row.get("status") != "open":
            return False
        client_nm = client_row["client_display_name"]
        await insert_relay_message(
            session,
            session_id=sid,
            sender_role=RELAY_SENDER_CLIENT,
            body_text=raw,
        )
        await session.commit()
    if trainer_tg is None:
        logger.warning("relay_client_reply_no_trainer_tg sid=%s", sid)
        return True
    try:
        await send_trainer_relay_from_client(
            trainer_telegram_id=int(trainer_tg),
            client_display_name=client_nm,
            body_text=raw,
            session_id=sid,
        )
    except Exception:
        logger.exception("relay_delivery_client_to_trainer_failed sid=%s", sid)
        return True
    tg_tr = int(trainer_tg)
    # Same UX as client side: trainer can reply with the next message without tapping «Ответить».
    # Skip when another text-awaiting workflow is active (those handlers consume the next message).
    if tg_tr not in trainer_support_awaiting and tg_tr not in trainer_booking_note_awaiting:
        set_trainer_relay_reply_pending(tg_tr, sid)
    return True


async def on_client_bot_relay_reply_callback(callback: CallbackQuery) -> None:
    """Mirrors trainer «Ответить»: reassurance + RBAC check (optional; text routes without this too)."""
    sid = _relay_callback_session_id(callback.data, "rly_ck:")
    if sid is None:
        await callback.answer("Неверная кнопка.", show_alert=True)
        return
    uid = callback.from_user.id if callback.from_user else 0
    if not uid:
        await callback.answer()
        return
    await callback.answer()
    if not callback.message:
        return
    await sweep_idle_relay_sessions_and_notify()
    async with async_session_factory() as session:
        row = await relay_session_context_for_id(session, session_id=int(sid))
        if (
            not row
            or row.get("status") != "open"
            or int(row.get("client_telegram_id") or 0) != int(uid)
        ):
            await callback.message.answer("<b>Сессия переписки уже недоступна.</b>")
            return
    await callback.message.answer(msg.CLIENT_RELAY_REPLY_PROMPT)


async def on_client_bot_relay_close_callback(callback: CallbackQuery) -> bool:
    """
    Parses callback_data ``rly_xc:{sid}``. Returns True when handled (even when session already closed).
    """
    data_raw = callback.data or ""
    if not data_raw.startswith("rly_xc:"):
        return False
    suffix = data_raw.split(":", 1)[1] if ":" in data_raw else ""
    try:
        sid = int(suffix)
    except ValueError:
        await callback.answer("Неверная кнопка.", show_alert=True)
        return True
    cid = callback.from_user.id if callback.from_user else 0
    if not cid:
        await callback.answer()
        return True
    async with async_session_factory() as session:
        row = await relay_session_context_for_id(session, session_id=sid)
        if not row or int(row["client_telegram_id"]) != int(cid):
            await callback.answer("Эта кнопка не для вас.", show_alert=True)
            return True
        await close_relay_session(session, session_id=sid)
        await session.commit()
    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await send_client_plain_notification(
        telegram_chat_id=int(cid),
        html_text=msg.CLIENT_RELAY_SESSION_CLOSED_HINT,
    )
    return True


async def deliver_trainer_pending_relay_reply(
    *,
    trainer_id: int,
    trainer_telegram_id: int,
    session_id: int,
    body_text: str,
) -> None:
    raw = sanitize_relay_body(body_text)
    if raw is None:
        return
    await sweep_idle_relay_sessions_and_notify()
    async with async_session_factory() as session:
        row = await relay_session_context_for_id(session, session_id=int(session_id), trainer_id=int(trainer_id))
        if not row or row.get("status") != "open":
            await send_trainer_plain_notification(
                telegram_chat_id=trainer_telegram_id,
                html_text="<b>Сессия переписки уже закрыта.</b>",
            )
            return
        c_tg = row.get("client_telegram_id")
        nm = await trainer_public_display_name(session, trainer_id=trainer_id)
        await insert_relay_message(
            session,
            session_id=int(session_id),
            sender_role=RELAY_SENDER_TRAINER,
            body_text=raw,
        )
        await session.commit()
    if not c_tg:
        logger.warning("relay_trainer_reply_no_client_tg sid=%s", session_id)
        return
    await send_client_relay_from_trainer(
        client_telegram_id=int(c_tg),
        trainer_display_name=nm,
        body_text=raw,
        session_id=int(session_id),
    )

