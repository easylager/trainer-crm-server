"""Trainer one-time «share catalog / deep link» tip after first booking milestone."""

from __future__ import annotations

import html

from aiogram import Bot
from aiogram.enums import ParseMode

from src.application.booking_use_cases import get_trainer_default_city_and_service
from src.application.trainer_invite_links import build_trainer_invite_links
from src.application.trainer_use_cases import get_trainer
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory
from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE
from src.shared.config import Settings
from src.shared.trainer_status import normalize_trainer_status_value


async def send_trainer_share_catalog_tip_to_chat(
    *,
    bot: Bot,
    chat_id: int,
    trainer_id: int,
) -> None:
    """
    Second message after the first booking: growth tip, aligned with catalog reality.

    Inactive / pending trainers are not listed in the public catalog — prioritize moderation/activation
    and only push the personal deep link; full «catalog + deep link» pitch when active and visible.
    """
    settings = Settings()
    async with async_session_factory() as session:
        trainer = await get_trainer(session, trainer_id)
        city_id, service_id = await get_trainer_default_city_and_service(session, trainer_id)
    links, err = build_trainer_invite_links(
        webapp_base_url=settings.webapp_base_url,
        client_bot_username=settings.client_bot_username,
        city_id=city_id,
        service_id=service_id,
        trainer_id=trainer_id,
    )
    if err == "missing_username":
        await bot.send_message(chat_id=chat_id, text=msg.TRAINER_SHARE_CATALOG_TIP_NO_CLIENT_BOT, parse_mode=ParseMode.HTML)
        return
    if err == "missing_city_or_service":
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_SHARE_CATALOG_TIP_PROFILE_INCOMPLETE,
            parse_mode=ParseMode.HTML,
        )
        return
    assert links is not None
    deep_esc = html.escape(links.client_bot_deep_link)
    st = normalize_trainer_status_value(trainer.get("status") if trainer else None)
    catalog_visible = bool((trainer or {}).get("is_catalog_visible", True))
    in_public_catalog = st == TRAINER_STATUS_ACTIVE and catalog_visible

    if not in_public_catalog:
        if st != TRAINER_STATUS_ACTIVE:
            tip = msg.TRAINER_SHARE_FIRST_BOOKING_CATALOG_PATH_HTML
            from src.bot.handlers.trainer_handlers import _trainer_profile_keyboard

            await bot.send_message(
                chat_id=chat_id,
                text=tip,
                parse_mode=ParseMode.HTML,
                reply_markup=_trainer_profile_keyboard(),
            )
            return
        elif links.catalog_page_url:
            cat_esc = html.escape(links.catalog_page_url)
            tip = msg.TRAINER_SHARE_FIRST_BOOKING_ACTIVE_HIDDEN_FROM_CATALOG_HTML.format(
                deep_link=deep_esc,
                catalog_url=cat_esc,
            )
        else:
            tip = msg.TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML.format(deep_link=deep_esc)
        await bot.send_message(chat_id=chat_id, text=tip, parse_mode=ParseMode.HTML)
        return

    if links.catalog_page_url:
        cat_esc = html.escape(links.catalog_page_url)
        tip = msg.TRAINER_SHARE_CATALOG_TIP_BOTH_HTML.format(deep_link=deep_esc, catalog_url=cat_esc)
    else:
        tip = msg.TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML.format(deep_link=deep_esc)
    await bot.send_message(chat_id=chat_id, text=tip, parse_mode=ParseMode.HTML)
