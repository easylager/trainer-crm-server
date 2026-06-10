"""Client-bot push: «Вас записали на занятие» after trainer-initiated booking."""

from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_payment_notice import classify_booking_expected_payment_class
from src.application.booking_use_cases import (
    claim_client_trainer_booked_notification,
    fetch_trainer_booked_notification_payload,
    release_client_trainer_booked_notification_claim,
)
from src.bot import messages as msg

logger = logging.getLogger(__name__)


def _slot_display_strings(slot_date, start_time) -> tuple[str, str, str]:
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = (
        msg.TRAINER_DAYS[slot_date.weekday()]
        if slot_date and hasattr(slot_date, "weekday")
        else ""
    )
    time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
    return date_str, day_str, time_str


async def try_send_client_trainer_booked_push(
    session: AsyncSession,
    client_bot: Bot,
    booking_id: int,
    *,
    webapp_base_url: str | None = None,
) -> bool:
    """
    Send rich «Вас записали…» when booking is still eligible (trainer-created, not yet notified).
    Resolves pass/cert coverage at send time so copy matches client booking cards.
    """
    bid = int(booking_id)
    if not await claim_client_trainer_booked_notification(session, bid):
        return False

    p = await fetch_trainer_booked_notification_payload(session, bid)
    chat_id = (p or {}).get("client_telegram_id")
    trainer_id = (p or {}).get("trainer_id")
    if not p or not chat_id or trainer_id is None:
        await release_client_trainer_booked_notification_claim(session, bid)
        return False

    payment_class = await classify_booking_expected_payment_class(
        session, bid, int(trainer_id)
    )
    date_str, day_str, time_str = _slot_display_strings(p.get("slot_date"), p.get("start_time"))
    text = msg.format_client_trainer_booked_you_html(
        date=date_str,
        day=day_str,
        time=time_str,
        trainer_name=str(p.get("trainer_name") or "Тренер"),
        service_name=p.get("service_name"),
        booking_price_cents=p.get("booking_price_cents"),
        price_tier_label=p.get("price_tier_label"),
        arena_name=p.get("arena_name"),
        arena_address=p.get("arena_address"),
        duration_minutes=p.get("duration_minutes"),
        map_link=p.get("map_link"),
        expected_payment_class=payment_class,
    )
    kb = msg.build_client_trainer_booked_you_inline_keyboard(
        booking_id=bid,
        map_url=p.get("map_link"),
        webapp_base_url=webapp_base_url,
    )
    try:
        await client_bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
    except Exception as e:
        logger.warning(
            "Trainer-booked notify to client %s (booking_id=%s): %s",
            chat_id,
            bid,
            e,
        )
        await release_client_trainer_booked_notification_claim(session, bid)
        return False
    return True
