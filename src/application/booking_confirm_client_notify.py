"""Client Telegram notification after trainer confirms a pending booking."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_payment_notice import classify_booking_expected_payment_class
from src.application.trainer_use_cases import get_trainer
from src.bot import messages as msg
from src.shared.config import Settings

TRAINER_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
logger = logging.getLogger(__name__)


async def notify_client_booking_confirmed_by_trainer(
    session: AsyncSession,
    trainer_id: int,
    booking_id: int,
    info: dict,
) -> bool:
    """
    Send «Ваша запись подтверждена» to the client bot — same semantics as webapp confirm route.

    Returns True once Telegram accepted the message. Callers must only mark the booking as
    notified (``client_notified_trainer_booked_at``) on a True return — a caught send failure
    here used to still leave that flag set, which meant the client silently never got any
    confirmation and the fallback «Вас записали» push couldn't retry either (both blocked by
    the same flag). See ``get_pending_booking_confirmed_notifications`` for the retry loop.
    """
    client_tid = info.get("client_telegram_id")
    if not client_tid:
        return False
    d = info["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    dow = TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    time_str = (
        info["start_time"].strftime("%H:%M")
        if hasattr(info["start_time"], "strftime")
        else str(info["start_time"])[:5]
    )
    trainer_obj = await get_trainer(session, trainer_id)
    profile = (trainer_obj or {}).get("profile") or {}
    trainer_name = (
        ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip()
        or "Тренер"
    )
    settings = Settings()
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    expected_payment_class = await classify_booking_expected_payment_class(session, booking_id, trainer_id)
    text_client = msg.format_client_booking_confirmed_by_trainer_text(
        date=date_str,
        day=dow,
        time=time_str,
        trainer_name=trainer_name,
        service_name=info.get("service_name"),
        booking_price_cents=info.get("booking_price_cents"),
        price_tier_label=info.get("price_tier_label"),
        arena_name=info.get("arena_name"),
        arena_address=info.get("arena_address"),
        trainer_first_booking_milestone=bool(info.get("first_booking_milestone")),
        expected_payment_class=expected_payment_class,
    )
    reply_markup = msg.build_client_booking_confirmed_inline_keyboard(
        map_url=info.get("map_link"),
        trainer_telegram_id=info.get("trainer_telegram_id"),
    )
    try:
        await client_bot.send_message(
            chat_id=client_tid,
            text=text_client,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.warning(
            "Booking-confirmed notify to client %s (booking_id=%s): %s", client_tid, booking_id, e
        )
        return False
    finally:
        await client_bot.session.close()
    return True
