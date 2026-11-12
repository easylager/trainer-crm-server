"""
Immediate Telegram notify to client when trainer cancels a booking.
Also used by the background cancel notifier (shared formatting + mark sent),
including the one-per-rule «постоянное время снято» message.
"""
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    get_pending_cancel_notification_for_booking,
    mark_booking_cancel_notification_sent,
)
from src.application.recurring_use_cases import (
    claim_recurring_removed_notice,
    list_pending_recurring_removed_notices,
    release_recurring_removed_notice_claim,
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
    text = msg.format_client_booking_cancelled_html(
        date=date_str,
        day=day_str,
        time=time_str,
        by_trainer=True,
        booked_for_name=p.get("booked_for_name"),
    )
    try:
        await client_bot.send_message(chat_id=chat_id, text=text)
        await mark_booking_cancel_notification_sent(session, p["id"])
        return True
    except Exception as e:
        logger.warning("Cancel notify send to client %s: %s", chat_id, e)
        return False


def _recurring_notice_undeliverable(exc: Exception) -> bool:
    """Blocked bot / deleted chat: retrying forever every drain would only spam the log."""
    if isinstance(exc, TelegramForbiddenError):
        return True
    return isinstance(exc, TelegramBadRequest) and "chat not found" in str(exc).lower()


async def send_recurring_removed_notice(client_bot: Bot, session: AsyncSession, p: dict) -> bool:
    """
    Deliver one queued «постоянное время снято» (one per closed rule, not per booking).
    Claims the row first so parallel drains cannot double-send; a transient failure releases it.
    """
    rid = int(p["id"])
    chat_id = p.get("client_telegram_id")
    if not chat_id:
        return False
    if not await claim_recurring_removed_notice(session, rid):
        return False
    dow = int(p.get("day_of_week") or 0)
    st, et = p.get("start_time"), p.get("end_time")
    st_s = st.strftime("%H:%M") if hasattr(st, "strftime") else "—"
    et_s = et.strftime("%H:%M") if hasattr(et, "strftime") else ""
    text = msg.format_client_recurring_removed_by_trainer_notification_html(
        trainer_name=str(p.get("trainer_name") or "Тренер"),
        weekday_short=msg.TRAINER_DAYS[dow] if 0 <= dow < len(msg.TRAINER_DAYS) else "—",
        time_range=f"{st_s}–{et_s}" if et_s else st_s,
        booked_for_name=p.get("booked_for_name"),
    )
    try:
        await client_bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception as e:
        logger.warning("Recurring removed notice to client %s (rule %s): %s", chat_id, rid, e)
        if not _recurring_notice_undeliverable(e):
            await release_recurring_removed_notice_claim(session, rid)
        return False


async def process_recurring_removed_notices_batch(client_bot: Bot, session: AsyncSession) -> None:
    for p in await list_pending_recurring_removed_notices(session):
        await send_recurring_removed_notice(client_bot, session, p)


async def send_trainer_cancel_notification_for_booking_now(
    client_bot: Bot, session: AsyncSession, booking_id: int
) -> bool:
    """After cancel_booking(): notify client immediately (does not depend on notification_service)."""
    p = await get_pending_cancel_notification_for_booking(session, booking_id)
    if not p:
        return False
    return await send_cancel_notification_payload(client_bot, session, p)
