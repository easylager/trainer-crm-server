"""Push new support tickets to admin Telegram (HTML + reply keyboard)."""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.support_use_cases import get_support_message
from src.application.subscription_invoice_admin_notify import (
    trainer_contact_link_html,
    trainer_contact_url,
)
from src.infrastructure.db import async_session_factory
from src.infrastructure.db.models import SUPPORT_FROM_CLIENT, SUPPORT_FROM_TRAINER
from src.shared.config import Settings

logger = logging.getLogger(__name__)

# Must match ``ADMIN_SUPPORT_REPLY_PREFIX`` in admin_handlers.
ADMIN_SUPPORT_REPLY_CALLBACK_PREFIX = "admin:support:reply:"


async def _sender_row(session: AsyncSession, *, telegram_id: int, from_role: str) -> dict[str, Any]:
    if from_role == SUPPORT_FROM_TRAINER:
        r = await session.execute(
            text(
                """
                SELECT COALESCE(NULLIF(TRIM(COALESCE(tp.first_name, '') || ' ' || COALESCE(tp.last_name, '')), ''), ''),
                       NULLIF(TRIM(t.telegram_username), ''), t.telegram_id
                FROM trainers t
                LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
                WHERE t.telegram_id = :tg
                """
            ),
            {"tg": telegram_id},
        )
    else:
        r = await session.execute(
            text(
                """
                SELECT COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), ''),
                       NULLIF(TRIM(c.telegram_username), ''), c.telegram_id
                FROM clients c
                WHERE c.telegram_id = :tg
                """
            ),
            {"tg": telegram_id},
        )
    row = r.fetchone()
    if not row:
        return {"display_name": f"id {telegram_id}", "telegram_username": None, "telegram_id": telegram_id}
    dn = (row[0] or "").strip() or f"id {telegram_id}"
    un = (row[1] or "").strip() or None
    tid = int(row[2]) if row[2] is not None else int(telegram_id)
    return {"display_name": dn, "telegram_username": un, "telegram_id": tid}


def _build_admin_support_new_ticket_body(
    *,
    support_id: int,
    from_role: str,
    display_name: str,
    telegram_username: str | None,
    telegram_id: int,
    message_text: str,
    source_tag: str,
) -> str:
    role_ru = "тренер" if from_role == SUPPORT_FROM_TRAINER else "клиент"
    url = trainer_contact_url(telegram_id, telegram_username)
    if url:
        link_line = f'<a href="{html.escape(url)}">Открыть личку в Telegram</a>'
    else:
        link_line = trainer_contact_link_html(telegram_id, telegram_username)
    body_plain = (message_text or "").strip()
    if len(body_plain) > 3200:
        body_plain = body_plain[:3197] + "..."
    msg_block = html.escape(body_plain)
    tag_esc = html.escape(source_tag)
    return (
        f"💬 <b>Новое обращение #{support_id}</b> · {html.escape(role_ru)}\n"
        f"<i>{tag_esc}</i>\n\n"
        f"<b>{html.escape(display_name)}</b>\n"
        f"{link_line}\n\n"
        f"{msg_block}"
    )


def _reply_keyboard(support_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✉️ Ответить #{support_id}",
                    callback_data=f"{ADMIN_SUPPORT_REPLY_CALLBACK_PREFIX}{support_id}",
                ),
            ],
        ]
    )


async def notify_admins_new_support_ticket(support_id: int, *, source_tag: str = "форма в хабе") -> None:
    """Deliver one HTML card per admin; failures logged only."""
    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids:
        return
    async with async_session_factory() as session:
        ticket = await get_support_message(session, support_id)
        if not ticket:
            logger.warning("support admin notify: ticket %s missing", support_id)
            return
        tid = int(ticket["from_telegram_id"])
        role = str(ticket["from_role"] or SUPPORT_FROM_CLIENT)
        sender = await _sender_row(session, telegram_id=tid, from_role=role)
    body = _build_admin_support_new_ticket_body(
        support_id=support_id,
        from_role=role,
        display_name=str(sender["display_name"]),
        telegram_username=sender.get("telegram_username"),
        telegram_id=int(sender["telegram_id"]),
        message_text=str(ticket.get("message_text") or ""),
        source_tag=source_tag,
    )
    kb = _reply_keyboard(support_id)
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in admin_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=body, reply_markup=kb)
            except Exception:
                logger.exception(
                    "support admin notify failed chat_id=%s support_id=%s",
                    chat_id,
                    support_id,
                )
    finally:
        await bot.session.close()
