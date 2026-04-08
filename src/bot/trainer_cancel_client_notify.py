"""
Immediate Telegram notify to client when trainer cancels a booking.
Also used by the background cancel notifier (shared formatting + mark sent).
"""
import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    get_pending_cancel_notification_for_booking,
    mark_booking_cancel_notification_sent,
)
from src.bot import messages as msg

logger = logging.getLogger(__name__)


async def send_cancel_notification_payload(
    client_bot: Bot, session: AsyncSession, p: dict
) -> bool:
    """
    Send one queued «trainer cancelled» message and mark row sent.
    Returns True if Telegram accepted the message and DB was updated.
    """
    chat_id = p.get("client_telegram_id")
    if not chat_id:
        return False
    slot_date = p.get("slot_date")
    start_time = p.get("start_time")
    date_str = (
        slot_date.strftime("%d.%m")
        if slot_date and hasattr(slot_date, "strftime")
        else "—"
    )
    day_str = (
        msg.TRAINER_DAYS[slot_date.weekday()]
        if slot_date and hasattr(slot_date, "weekday")
        else ""
    )
    time_str = (
        start_time.strftime("%H:%M")
        if start_time and hasattr(start_time, "strftime")
        else "—"
    )
    text = msg.CLIENT_BOOKING_CANCELLED_BY_TRAINER.format(
        date=date_str, day=day_str, time=time_str
    )
    try:
        await client_bot.send_message(chat_id=chat_id, text=text)
        await mark_booking_cancel_notification_sent(session, p["id"])
        return True
    except Exception as e:
        logger.warning("Cancel notify send to client %s: %s", chat_id, e)
        return False


async def send_trainer_cancel_notification_for_booking_now(
    client_bot: Bot, session: AsyncSession, booking_id: int
) -> bool:
    """After cancel_booking(): notify client immediately (does not depend on notification_service)."""
    p = await get_pending_cancel_notification_for_booking(session, booking_id)
    if not p:
        return False
    return await send_cancel_notification_payload(client_bot, session, p)
