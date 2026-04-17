"""
Event-driven notifications after schedule change: no polling.
Run once when trainer applies template or adds slots — notify (1) clients waiting for
"repeat same time" slot, (2) trainer who said "remind when I have slots" for a request.
Called from trainer_handlers; client_bot is injected by trainer_app so we can send to clients.
"""
import asyncio
import html
import logging

from aiogram import Bot
from sqlalchemy import text as sql_text
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.application.client_request_use_cases import (
    get_trainers_pending_request_with_slots,
    mark_trainer_pending_request_reminder_sent,
)
from src.application.recurring_use_cases import (
    list_wait_requests_with_available_slots,
    mark_wait_request_notified,
)
from src.application.trainer_schedule_use_cases import next_week_monday, this_week_monday
from src.application.trainer_use_cases import get_trainer
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)

# Injected by trainer_app so we can send client-side "slot available" messages
_client_bot: Bot | None = None

REQUESTS_CALLBACK = "requests"


def set_client_bot(bot: Bot | None) -> None:
    global _client_bot
    _client_bot = bot


def _requests_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "заявка"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "заявки"
    return "заявок"


async def run_after_schedule_changed(trainer_id: int, trainer_bot: Bot) -> None:
    """
    Fire-and-forget: notify (1) clients with slot-wait requests that a slot appeared,
    (2) this trainer if they have "remind when slots" pending and now have slots.
    Intended to be run as asyncio.create_task(...) so the handler returns immediately.
    """
    try:
        # Short delay so the schedule change commit is visible to this task's queries
        await asyncio.sleep(0.5)
        # --- 1) Client: "repeat same time" → slot appeared (this week or next) ---
        client_bot = _client_bot
        if client_bot:
            async with async_session_factory() as session:
                trainer = await get_trainer(session, trainer_id)
            profile = (trainer or {}).get("profile") or {}
            trainer_name = ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip() or "Тренер"
            for from_date in (this_week_monday(), next_week_monday()):
                async with async_session_factory() as session:
                    items = await list_wait_requests_with_available_slots(session, from_date)
                for item in items:
                    if item.get("trainer_id") != trainer_id:
                        continue
                    chat_id = item.get("client_telegram_id")
                    if not chat_id:
                        continue
                    slot_date = item.get("slot_date")
                    start_time = item.get("start_time")
                    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
                    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
                    time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
                    message_text = msg.CLIENT_SLOT_AVAILABLE.format(
                        date=html.escape(date_str),
                        day=html.escape(day_str),
                        time=html.escape(time_str),
                        trainer_name=html.escape(trainer_name),
                    )
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=msg.CLIENT_BUTTON_BOOK_THIS_SLOT,
                            callback_data=f"book_available_slot:{item['slot_id']}",
                        )],
                    ])
                    try:
                        await client_bot.send_message(chat_id=chat_id, text=message_text, reply_markup=kb)
                        async with async_session_factory() as session:
                            await mark_wait_request_notified(session, item["id"])
                        logger.info("schedule_notify: sent slot_available to client %s (wait_id=%s)", chat_id, item["id"])
                    except Exception as e:
                        logger.warning("schedule_notify: client send to %s: %s", chat_id, e)

        # --- 2) Trainer: "remind when I have slots" for this trainer ---
        # Sent only if: trainer has >=1 row in trainer_pending_request_booking,
        # request not archived, >=1 available slot in next 14 days; not more than once per cooldown (default 3h).
        cooldown_minutes = Settings().schedule_reminder_cooldown_minutes
        async with async_session_factory() as session:
            pending = await get_trainers_pending_request_with_slots(session, cooldown_minutes=cooldown_minutes)
        items_for_trainer = [p for p in pending if p.get("trainer_id") == trainer_id]
        if items_for_trainer:
            logger.info("schedule_notify: trainer_id=%s pending_total=%s items_for_trainer=%s", trainer_id, len(pending), len(items_for_trainer))
        if not items_for_trainer:
            # Diagnose why: no pending rows, request archived, no slots in window, or reminder sent recently
            async with async_session_factory() as session:
                r1 = await session.execute(
                    sql_text("""
                        SELECT
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE r.status = 'archived') AS archived,
                            COUNT(*) FILTER (WHERE p.last_reminder_sent_at >= NOW() - INTERVAL '3 hours') AS reminder_recent
                        FROM trainer_pending_request_booking p
                        JOIN client_requests r ON r.id = p.client_request_id
                        WHERE p.trainer_id = :tid
                    """),
                    {"tid": trainer_id},
                )
                row1 = r1.fetchone()
                r2 = await session.execute(
                    sql_text("""
                        SELECT COUNT(*) FROM slots
                        WHERE trainer_id = :tid AND slot_date >= CURRENT_DATE
                          AND slot_date <= CURRENT_DATE + INTERVAL '14 days' AND status = 'available'
                    """),
                    {"tid": trainer_id},
                )
                slots_count = (r2.fetchone() or (0,))[0]
            pending_count = (row1[0] or 0) if row1 else 0
            archived_count = (row1[1] or 0) if row1 else 0
            reminder_recent = (row1[2] or 0) if row1 and len(row1) > 2 else 0
            logger.info(
                "schedule_notify: trainer_id=%s pending_total=0 | pending_rows=%s archived=%s reminder_sent_last_3h=%s available_slots_14d=%s",
                trainer_id, pending_count, archived_count, reminder_recent, slots_count,
            )
            return
        telegram_id = items_for_trainer[0].get("trainer_telegram_id")
        if not telegram_id:
            return
        count = len(items_for_trainer)
        reminder_text = msg.TRAINER_PENDING_BOOKING_REMINDER.format(
            count=count,
            requests_word=_requests_word(count),
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_REQUESTS, callback_data=REQUESTS_CALLBACK)],
        ])
        try:
            await trainer_bot.send_message(chat_id=telegram_id, text=reminder_text, reply_markup=kb)
            async with async_session_factory() as session:
                for p in items_for_trainer:
                    await mark_trainer_pending_request_reminder_sent(
                        session, p["trainer_id"], p["client_request_id"]
                    )
            logger.info("schedule_notify: trainer_id=%s sent pending_request reminder count=%s", trainer_id, count)
        except Exception as e:
            logger.warning("schedule_notify: trainer send to %s: %s", telegram_id, e)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception("schedule_notify: %s", e)
