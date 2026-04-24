"""
Send «free slots next week» nudges from the client bot after trainer picks clients in the hub.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import get_trainer_client_for_card
from src.application.subscription_tier_use_cases import trainer_allows_online_booking
from src.application.trainer_use_cases import get_trainer
from src.bot import messages as msg
from src.shared.config import Settings

logger = logging.getLogger(__name__)


def _trainer_display_name(trainer: dict | None) -> str:
    if not trainer:
        return "Тренер"
    profile = trainer.get("profile") or {}
    first = (profile.get("first_name") or "").strip()
    last = (profile.get("last_name") or "").strip()
    return (first + " " + last).strip() or "Тренер"


async def send_trainer_fill_slots_invites(
    session: AsyncSession,
    trainer_id: int,
    client_ids: list[int],
) -> dict[str, Any]:
    """
    For each client_id (unique, order preserved): trainer must see the client in CRM; client must
    have telegram_id. Sends HTML message + WebApp «Записаться» when HTTPS base URL is configured.
    """
    seen: set[int] = set()
    ordered: list[int] = []
    for raw in client_ids:
        cid = int(raw)
        if cid in seen:
            continue
        seen.add(cid)
        ordered.append(cid)

    trainer = await get_trainer(session, trainer_id)
    trainer_name = _trainer_display_name(trainer)
    online = await trainer_allows_online_booking(session, trainer_id)
    settings = Settings()
    kb = msg.build_client_fill_slots_invite_keyboard(
        webapp_base_url=settings.webapp_base_url,
        trainer_id=trainer_id,
        online_booking=online,
    )

    sent: list[int] = []
    failed: list[dict[str, Any]] = []
    skipped_no_telegram: list[int] = []

    bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        for i, cid in enumerate(ordered):
            card = await get_trainer_client_for_card(session, trainer_id, cid)
            if not card:
                failed.append({"client_id": cid, "detail": "Нет доступа к клиенту"})
                continue
            chat_id_raw = card.get("telegram_id")
            if chat_id_raw is None:
                skipped_no_telegram.append(cid)
                continue
            chat_id = int(chat_id_raw)
            first = (card.get("first_name") or "").strip()
            text_html = msg.format_client_fill_slots_invite_from_trainer_html(
                client_first_name=first or None,
                trainer_display_name=trainer_name,
                variant_index=i,
            )
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text_html,
                    reply_markup=kb,
                )
                sent.append(cid)
            except Exception as e:  # noqa: BLE001
                logger.warning("fill_slots_invite send failed client_id=%s: %s", cid, e)
                failed.append({"client_id": cid, "detail": str(e)[:220]})
    finally:
        await bot.session.close()

    return {
        "sent": sent,
        "failed": failed,
        "skipped_no_telegram": skipped_no_telegram,
    }
