"""Trainer notifications when a client joins CRM through a public invite form."""
from __future__ import annotations

import html
import logging
from typing import Literal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_client_scope import list_trainer_ids_for_client_crm_scope

from src.application.booking_use_cases import get_trainer_telegram_id
from src.bot import messages as msg
from src.shared.config import Settings

logger = logging.getLogger(__name__)

TrainerClientRegistrationEvent = Literal["new_client", "telegram_linked"]


async def _client_display_label(session: AsyncSession, client_id: int) -> str:
    r = await session.execute(
        text(
            """
            SELECT first_name, last_name, phone, telegram_username
            FROM clients
            WHERE id = :cid
            LIMIT 1
            """
        ),
        {"cid": client_id},
    )
    row = r.mappings().first()
    if not row:
        return "Клиент"

    first_name = (row.get("first_name") or "").strip()
    last_name = (row.get("last_name") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name

    phone = (row.get("phone") or "").strip()
    if phone:
        return phone

    username = (row.get("telegram_username") or "").strip().lstrip("@")
    if username:
        return f"@{username}"

    return "Клиент"


def _trainer_client_profile_markup(client_id: int) -> InlineKeyboardMarkup | None:
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None

    url = f"{base}/webapp/trainer-clients?client_id={int(client_id)}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_CLIENT_REGISTERED_OPEN_PROFILE_BTN,
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


async def notify_trainer_client_registered_from_invite(
    *,
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    event: TrainerClientRegistrationEvent,
) -> None:
    """Best-effort Telegram push to trainer after public invite self-registration."""
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return

    trainer_tid = await get_trainer_telegram_id(session, trainer_id)
    if not trainer_tid:
        return

    label = html.escape(await _client_display_label(session, client_id))
    if event == "telegram_linked":
        text = msg.TRAINER_CLIENT_REGISTERED_LINKED_HTML.format(client_label=label)
    else:
        text = msg.TRAINER_CLIENT_REGISTERED_NEW_HTML.format(client_label=label)

    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(
            chat_id=int(trainer_tid),
            text=text,
            reply_markup=_trainer_client_profile_markup(client_id),
        )
    except Exception:
        logger.exception(
            "Failed to send trainer client-registration notification trainer_id=%s client_id=%s event=%s",
            trainer_id,
            client_id,
            event,
        )
    finally:
        await bot.session.close()


async def _member_telegram_label(username: str | None, telegram_id: int) -> str:
    u = (username or "").strip().lstrip("@")
    if u:
        return html.escape(f"@{u}")
    return html.escape(f"Telegram id {int(telegram_id)}")


async def notify_trainers_family_access_member_joined(
    *,
    session: AsyncSession,
    primary_client_id: int,
    member_telegram_id: int,
    member_telegram_username: str | None = None,
) -> None:
    """Notify each trainer on roster: new Telegram joined shared family client card."""
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return
    trainer_ids = await list_trainer_ids_for_client_crm_scope(session, int(primary_client_id))
    if not trainer_ids:
        return
    client_label = html.escape(await _client_display_label(session, int(primary_client_id)))
    member_label = await _member_telegram_label(member_telegram_username, int(member_telegram_id))
    text_html = msg.TRAINER_CLIENT_FAMILY_MEMBER_HTML.format(
        client_label=client_label,
        member_label=member_label,
    )
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        markup = _trainer_client_profile_markup(int(primary_client_id))
        for tid in trainer_ids:
            trainer_tid = await get_trainer_telegram_id(session, tid)
            if not trainer_tid:
                continue
            try:
                await bot.send_message(
                    chat_id=int(trainer_tid),
                    text=text_html,
                    reply_markup=markup,
                )
            except Exception:
                logger.exception(
                    "family access notify failed trainer_id=%s client_id=%s",
                    tid,
                    primary_client_id,
                )
    finally:
        await bot.session.close()
