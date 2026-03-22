"""
Notification loops: read from DB and send Telegram messages.
Used by notification_service (standalone process). Client/trainer apps no longer run these.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from src.application.booking_use_cases import (
    get_booking_no_pass_notify_payload,
    get_bookings_pending_notification,
    get_clients_for_inactive_notification,
    get_pending_booking_cancel_notifications,
    get_pending_completed_for_trainer,
    get_pending_trainer_booked_notifications,
    get_trainer_telegram_id,
    INACTIVE_KIND_10_DAYS,
    INACTIVE_KIND_30_DAYS,
    list_bookings_pending_confirm_reminder,
    list_bookings_to_complete,
    list_pending_reminders,
    mark_booking_cancel_notification_sent,
    mark_booking_completed_and_notify,
    mark_booking_notified,
    mark_confirm_reminder_sent,
    mark_inactive_notification_sent,
    mark_reminder_failed,
    mark_reminder_sent,
    mark_trainer_booked_notified,
    mark_trainer_completed_sent,
)
from src.application.client_request_use_cases import (
    get_pending_no_response_reminders,
    get_pending_request_notifications,
    get_pending_response_notifications,
    get_trainers_for_daily_request_reminder,
    mark_no_response_reminder_sent,
    mark_request_trainer_notified,
    mark_response_notified,
    mark_trainer_daily_request_reminder_sent,
)
from src.application.recurring_use_cases import get_slot_status_on_date
from src.application.certificate_use_cases import (
    expire_certificates_past_expiry,
    process_certificate_email_outbox_batch,
)
from src.application.subscription_use_cases import (
    expire_subscriptions_to_past_due,
    get_subscriptions_reminder_due,
    mark_subscription_reminder_sent,
)
from src.bot import messages as msg
from src.bot.handlers.trainer_handlers import REQUEST_DECLINE_PREFIX, REQUEST_RESPOND_PREFIX
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings
from src.shared.notification_hours import is_within_notification_hours

logger = logging.getLogger(__name__)

# Intervals (seconds)
REMINDER_INTERVAL_SEC = 60
BOOKING_COMPLETE_INTERVAL_SEC = 5 * 60
CANCEL_NOTIFIER_INTERVAL_SEC = 15
RESPONSE_NOTIFIER_INTERVAL_SEC = 20
NO_RESPONSE_REMINDER_INTERVAL_SEC = 60 * 60
TRAINER_BOOKED_NOTIFIER_INTERVAL_SEC = 30
INACTIVE_CLIENT_INTERVAL_SEC = 60 * 60 * 6
BOOKING_NOTIFIER_INTERVAL_SEC = 15
REQUEST_NOTIFIER_INTERVAL_SEC = 20
COMPLETED_FEEDBACK_INTERVAL_SEC = 20
DAILY_REQUEST_REMINDER_INTERVAL_SEC = 3 * 24 * 60 * 60
SUBSCRIPTION_LOOP_INTERVAL_SEC = 24 * 60 * 60  # once per day: expire + reminder
CERTIFICATE_OUTBOX_INTERVAL_SEC = 2 * 60  # every 2 min: retry failed certificate emails


def _slot_display_strings(slot_date, start_time):
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
    return date_str, day_str, time_str


def _reminder_duration_minutes(start_time, end_time) -> int:
    try:
        if start_time and end_time and hasattr(start_time, "hour") and hasattr(end_time, "hour"):
            delta = datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
            return max(0, int(delta.total_seconds() // 60))
    except (TypeError, ValueError):
        pass
    return 45


def _requests_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "заявка"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "заявки"
    return "заявок"


# --- Client loops (use client_bot) ---


async def run_reminder_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(REMINDER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await list_pending_reminders(session)
                for p in pending:
                    chat_id = p.get("client_telegram_id")
                    if not chat_id:
                        continue
                    date_str, day_str, time_str = _slot_display_strings(
                        p.get("slot_date"), p.get("start_time")
                    )
                    duration = _reminder_duration_minutes(p.get("start_time"), p.get("end_time"))
                    kind = p.get("kind") or ""
                    if kind == "before_24h":
                        text = msg.CLIENT_REMINDER_24H.format(
                            date=date_str, day=day_str, time=time_str, duration=duration
                        )
                    else:
                        text = msg.CLIENT_REMINDER_2H.format(
                            date=date_str, day=day_str, time=time_str, duration=duration
                        )
                    try:
                        await client_bot.send_message(chat_id=chat_id, text=text)
                        await mark_reminder_sent(session, p["id"])
                    except Exception as e:
                        logger.warning("Reminder send to client %s (reminder_id=%s): %s", chat_id, p["id"], e)
                        await mark_reminder_failed(session, p["id"], str(e))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Reminder loop: %s", e)


async def run_booking_complete_loop(client_bot: Bot, trainer_bot: Bot) -> None:
    logger.info("[booking_complete_loop] started")
    while True:
        try:
            await asyncio.sleep(BOOKING_COMPLETE_INTERVAL_SEC)
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                to_complete = await list_bookings_to_complete(session)
                if to_complete:
                    logger.info("booking_complete_loop: %s booking(s) to complete", len(to_complete))
                for b in to_complete:
                    pass_redeemed = await mark_booking_completed_and_notify(session, b["id"])
                    if not pass_redeemed:
                        no_pass_payload = await get_booking_no_pass_notify_payload(session, b["id"])
                        if no_pass_payload and no_pass_payload.get("trainer_telegram_id"):
                            try:
                                text = msg.TRAINER_NO_PASS_FOR_SERVICE.format(
                                    client_name=no_pass_payload["client_name"],
                                    date=no_pass_payload["date"],
                                    time=no_pass_payload["time"],
                                    service_name=no_pass_payload["service_name"],
                                )
                                await trainer_bot.send_message(
                                    chat_id=no_pass_payload["trainer_telegram_id"],
                                    text=text,
                                )
                            except Exception as e:
                                logger.warning(
                                    "No-pass notify to trainer %s: %s",
                                    no_pass_payload.get("trainer_telegram_id"),
                                    e,
                                )
                    chat_id = b.get("client_telegram_id")
                    if not chat_id:
                        continue
                    date_str, day_str, time_str = _slot_display_strings(
                        b.get("slot_date"), b.get("start_time")
                    )
                    text = msg.CLIENT_BOOKING_COMPLETED.format(
                        date=date_str, day=day_str, time=time_str
                    )
                    slot_date_val = b["slot_date"]
                    target_date = (
                        slot_date_val.date() if hasattr(slot_date_val, "date") else slot_date_val
                    ) + timedelta(days=7)
                    async with async_session_factory() as check_session:
                        status_next, _ = await get_slot_status_on_date(
                            check_session, b["trainer_id"], target_date, b["start_time"]
                        )
                    rows = [
                        [
                            InlineKeyboardButton(
                                text=msg.CLIENT_BUTTON_LEAVE_FEEDBACK,
                                callback_data=f"feedback_booking:{b['id']}",
                            )
                        ],
                    ]
                    if status_next != "booked":
                        rows.append([
                            InlineKeyboardButton(
                                text=msg.CLIENT_BUTTON_REPEAT_SAME_TIME,
                                callback_data=f"repeat_booking:{b['id']}",
                            ),
                            InlineKeyboardButton(
                                text=msg.CLIENT_BUTTON_BECOME_REGULAR,
                                callback_data=f"make_recurring:{b['id']}",
                            ),
                        ])
                    kb = InlineKeyboardMarkup(inline_keyboard=rows)
                    try:
                        await client_bot.send_message(
                            chat_id=chat_id, text=text, reply_markup=kb
                        )
                    except Exception as e:
                        logger.warning(
                            "Completed notifier send to client %s: %s", chat_id, e
                        )
        except asyncio.CancelledError:
            logger.info("[booking_complete_loop] cancelled")
            break
        except Exception as e:
            logger.exception("Booking complete loop: %s", e)


async def run_cancel_notifier_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(CANCEL_NOTIFIER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_pending_booking_cancel_notifications(session)
                for p in pending:
                    chat_id = p.get("client_telegram_id")
                    if not chat_id:
                        continue
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
                    try:
                        text = msg.CLIENT_BOOKING_CANCELLED_BY_TRAINER.format(
                            date=date_str, day=day_str, time=time_str
                        )
                        await client_bot.send_message(chat_id=chat_id, text=text)
                    except Exception as e:
                        logger.warning("Cancel notifier send to client %s: %s", chat_id, e)
                    await mark_booking_cancel_notification_sent(session, p["id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Cancel notifier: %s", e)


async def run_response_notifier_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(RESPONSE_NOTIFIER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_pending_response_notifications(session)
                for p in pending:
                    client_tid = p.get("client_telegram_id")
                    if not client_tid:
                        continue
                    if p.get("trainer_comment"):
                        text = msg.CLIENT_RESPONSE_NOTIFICATION_WITH_COMMENT.format(
                            responder_name=p.get("responder_name") or "Тренер",
                            comment=p.get("trainer_comment"),
                        )
                    else:
                        text = msg.CLIENT_RESPONSE_NOTIFICATION
                    request_id = p.get("request_id")
                    kb = None
                    if request_id is not None:
                        base = (Settings().webapp_base_url or "").rstrip("/")
                        if base.startswith("https://"):
                            url = f"{base}/webapp/client-requests?request_id={request_id}"
                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=msg.CLIENT_RESPONSE_BUTTON_VIEW,
                                        web_app=WebAppInfo(url=url),
                                    )
                                ],
                            ])
                        else:
                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=msg.CLIENT_RESPONSE_BUTTON_VIEW,
                                        callback_data=f"my_request:{request_id}",
                                    )
                                ],
                            ])
                    try:
                        await client_bot.send_message(
                            chat_id=client_tid, text=text, reply_markup=kb
                        )
                    except Exception as e:
                        logger.warning(
                            "Response notifier send to client %s: %s", client_tid, e
                        )
                    await mark_response_notified(session, p["response_id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Response notifier: %s", e)


async def run_no_response_reminder_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(NO_RESPONSE_REMINDER_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                pending = await get_pending_no_response_reminders(session)
                for p in pending:
                    client_tid = p.get("client_telegram_id")
                    if not client_tid:
                        continue
                    try:
                        await client_bot.send_message(
                            chat_id=client_tid, text=msg.CLIENT_NO_RESPONSE_REMINDER
                        )
                        await mark_no_response_reminder_sent(session, p["request_id"])
                    except Exception as e:
                        logger.warning(
                            "No-response reminder send to client %s (request_id=%s): %s",
                            client_tid,
                            p.get("request_id"),
                            e,
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("No-response reminder loop: %s", e)


async def run_trainer_booked_notifier_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(TRAINER_BOOKED_NOTIFIER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_pending_trainer_booked_notifications(session)
                for p in pending:
                    chat_id = p.get("client_telegram_id")
                    if not chat_id:
                        continue
                    date_str, day_str, time_str = _slot_display_strings(
                        p.get("slot_date"), p.get("start_time")
                    )
                    text = msg.CLIENT_TRAINER_BOOKED_YOU.format(
                        name=p.get("trainer_name") or "Тренер",
                        date=date_str,
                        day=day_str,
                        time=time_str,
                    )
                    try:
                        await client_bot.send_message(chat_id=chat_id, text=text)
                        await mark_trainer_booked_notified(session, p["booking_id"])
                    except Exception as e:
                        logger.warning(
                            "Trainer-booked notify to client %s (booking_id=%s): %s",
                            chat_id,
                            p.get("booking_id"),
                            e,
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Trainer-booked notifier: %s", e)


async def run_inactive_client_loop(client_bot: Bot) -> None:
    logger.info("[inactive_client_loop] started")
    while True:
        try:
            await asyncio.sleep(INACTIVE_CLIENT_INTERVAL_SEC)
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                for kind in (INACTIVE_KIND_10_DAYS, INACTIVE_KIND_30_DAYS):
                    clients = await get_clients_for_inactive_notification(session, kind)
                    if not clients:
                        continue
                    text_template = (
                        msg.CLIENT_INACTIVE_10_DAYS
                        if kind == INACTIVE_KIND_10_DAYS
                        else msg.CLIENT_INACTIVE_30_DAYS
                    )
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=msg.CLIENT_BUTTON_BOOK,
                                callback_data="catalog",
                            )
                        ],
                    ])
                    for c in clients:
                        chat_id = c.get("telegram_id")
                        if not chat_id:
                            continue
                        name = (c.get("first_name") or "").strip()
                        name_placeholder = f", {name}" if name else ""
                        text = text_template.format(name=name_placeholder)
                        try:
                            await client_bot.send_message(
                                chat_id=chat_id, text=text, reply_markup=kb
                            )
                            await mark_inactive_notification_sent(
                                session, c["client_id"], kind
                            )
                        except Exception as e:
                            logger.warning(
                                "Inactive notify to client %s (kind=%s): %s",
                                chat_id,
                                kind,
                                e,
                            )
        except asyncio.CancelledError:
            logger.info("[inactive_client_loop] cancelled")
            break
        except Exception as e:
            logger.exception("Inactive client loop: %s", e)


# --- Trainer loops (use trainer_bot) ---


async def run_booking_notifier_loop(trainer_bot: Bot) -> None:
    while True:
        await asyncio.sleep(BOOKING_NOTIFIER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_bookings_pending_notification(session)
                if pending:
                    logger.info(
                        "Booking notifier: %s pending booking(s) to send to trainer(s)",
                        len(pending),
                    )
                for b in pending:
                    trainer_tid = await get_trainer_telegram_id(session, b["trainer_id"])
                    if not trainer_tid:
                        await mark_booking_notified(session, b["id"])
                        continue
                    d = b["slot_date"]
                    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
                    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
                    time_str = (
                        f"{b['start_time'].strftime('%H:%M') if hasattr(b['start_time'], 'strftime') else b['start_time']}"
                        f"–{b['end_time'].strftime('%H:%M') if hasattr(b['end_time'], 'strftime') else b['end_time']}"
                    )
                    phone = b.get("client_phone") or "—"
                    comment = (b.get("client_comment") or "").strip()
                    client_name = b.get("client_name") or "Клиент"
                    service = b.get("service_name") or "—"
                    city = b.get("city_name") or "—"
                    arenas = b.get("arenas_str") or "—"
                    if comment:
                        text = msg.TRAINER_BOOKING_NOTIFICATION.format(
                            date=date_str,
                            day=dow,
                            time=time_str,
                            client_name=client_name,
                            phone=phone,
                            service=service,
                            city=city,
                            arenas=arenas,
                            comment=comment,
                        )
                    else:
                        text = msg.TRAINER_BOOKING_NOTIFICATION_NO_COMMENT.format(
                            date=date_str,
                            day=dow,
                            time=time_str,
                            client_name=client_name,
                            phone=phone,
                            service=service,
                            city=city,
                            arenas=arenas,
                        )
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKINGS_BUTTON_CONFIRM,
                                    callback_data=f"confirm_booking:{b['id']}",
                                ),
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKINGS_BUTTON_DECLINE,
                                    callback_data=f"decline_booking:{b['id']}",
                                ),
                            ],
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKINGS_BUTTON_WRITE,
                                    url=f"tg://user?id={b['client_telegram_id']}",
                                )
                            ],
                        ]
                    )
                    await trainer_bot.send_message(
                        chat_id=trainer_tid, text=text, reply_markup=kb
                    )
                    await mark_booking_notified(session, b["id"])

                remind_candidates = await list_bookings_pending_confirm_reminder(session)
                for r in remind_candidates:
                    trainer_tid = await get_trainer_telegram_id(
                        session, r["trainer_id"]
                    )
                    if not trainer_tid:
                        await mark_confirm_reminder_sent(session, r["booking_id"])
                        continue
                    d2 = r["slot_date"]
                    date_str2 = d2.strftime("%d.%m") if hasattr(d2, "strftime") else str(d2)
                    dow2 = msg.TRAINER_DAYS[d2.weekday()] if hasattr(d2, "weekday") else ""
                    start_time2 = r["start_time"]
                    time_str2 = (
                        start_time2.strftime("%H:%M")
                        if hasattr(start_time2, "strftime")
                        else str(start_time2)[:5]
                    )
                    client_display = r.get("client_phone") or "клиент"
                    text2 = msg.TRAINER_BOOKING_CONFIRM_REMINDER.format(
                        client_display=client_display,
                        date=date_str2,
                        day=dow2,
                        time=time_str2,
                    )
                    kb2 = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKINGS_BUTTON_CONFIRM,
                                    callback_data=f"confirm_booking:{r['booking_id']}",
                                ),
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKINGS_BUTTON_DECLINE,
                                    callback_data=f"decline_booking:{r['booking_id']}",
                                ),
                            ],
                        ]
                    )
                    await trainer_bot.send_message(
                        chat_id=trainer_tid, text=text2, reply_markup=kb2
                    )
                    await mark_confirm_reminder_sent(session, r["booking_id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Booking notifier: %s", e)


async def run_request_notifier_loop(trainer_bot: Bot) -> None:
    while True:
        await asyncio.sleep(REQUEST_NOTIFIER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_pending_request_notifications(session)
                for p in pending:
                    tid = p.get("trainer_telegram_id")
                    if not tid:
                        continue
                    comment = (p.get("comment") or "").strip()
                    if comment:
                        text = msg.TRAINER_REQUEST_NOTIFICATION.format(
                            city=p["city_name"],
                            service=p["service_name"],
                            comment=comment,
                        )
                    else:
                        text = msg.TRAINER_REQUEST_NOTIFICATION_NO_COMMENT.format(
                            city=p["city_name"],
                            service=p["service_name"],
                        )
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BUTTON_RESPOND,
                                    callback_data=f"{REQUEST_RESPOND_PREFIX}{p['request_id']}",
                                ),
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BUTTON_DECLINE,
                                    callback_data=f"{REQUEST_DECLINE_PREFIX}{p['request_id']}",
                                ),
                            ],
                        ]
                    )
                    try:
                        await trainer_bot.send_message(
                            chat_id=tid, text=text, reply_markup=kb
                        )
                    except Exception as e:
                        logger.warning(
                            "Request notifier send to %s: %s", tid, e
                        )
                    await mark_request_trainer_notified(
                        session, p["request_id"], p["trainer_id"]
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Request notifier: %s", e)


async def run_completed_feedback_loop(trainer_bot: Bot) -> None:
    while True:
        await asyncio.sleep(COMPLETED_FEEDBACK_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_pending_completed_for_trainer(session)
                for p in pending:
                    trainer_tid = await get_trainer_telegram_id(
                        session, p["trainer_id"]
                    )
                    if not trainer_tid:
                        await mark_trainer_completed_sent(session, p["id"])
                        continue
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
                    text = msg.TRAINER_BOOKING_COMPLETED.format(
                        date=date_str, day=day_str, time=time_str
                    )
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BUTTON_LEAVE_FEEDBACK,
                                    callback_data=f"feedback_booking_trainer:{p['booking_id']}",
                                )
                            ],
                        ]
                    )
                    try:
                        await trainer_bot.send_message(
                            chat_id=trainer_tid, text=text, reply_markup=kb
                        )
                    except Exception as e:
                        logger.warning(
                            "Completed feedback send to trainer %s: %s",
                            trainer_tid,
                            e,
                        )
                    await mark_trainer_completed_sent(session, p["id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Completed feedback loop: %s", e)


async def run_daily_request_reminder_loop(trainer_bot: Bot) -> None:
    while True:
        await asyncio.sleep(DAILY_REQUEST_REMINDER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                trainers = await get_trainers_for_daily_request_reminder(session)
                for p in trainers:
                    tid = p.get("trainer_telegram_id")
                    if not tid:
                        continue
                    count = p.get("request_count") or 0
                    if count <= 0:
                        continue
                    text = msg.TRAINER_DAILY_REQUESTS_REMINDER.format(
                        count=count,
                        requests_word=_requests_word(count),
                    )
                    try:
                        await trainer_bot.send_message(chat_id=tid, text=text)
                        await mark_trainer_daily_request_reminder_sent(
                            session, p["trainer_id"]
                        )
                    except Exception as e:
                        logger.warning(
                            "Daily request reminder to trainer %s (id=%s): %s",
                            tid,
                            p.get("trainer_id"),
                            e,
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Daily request reminder loop: %s", e)


async def run_subscription_expire_and_reminder_loop(trainer_bot: Bot) -> None:
    """Once per day: set past_due for expired subscriptions; send reminder N days before expiry (config: subscription_reminder_days_ahead)."""
    while True:
        await asyncio.sleep(SUBSCRIPTION_LOOP_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                # 1) Expire subscriptions that passed expires_at
                n = await expire_subscriptions_to_past_due(session)
                if n:
                    logger.info("Subscription expire: %d set to past_due", n)
                # 1b) Expire certificates past expires_at (issued/activated -> expired)
                cert_n = await expire_certificates_past_expiry(session)
                if cert_n:
                    logger.info("Certificate expire: %d set to expired", cert_n)
                # 2) Reminders for subscriptions expiring in the next 3 days
                if not is_within_notification_hours():
                    continue
                days_ahead = max(1, Settings().subscription_reminder_days_ahead)
                due = await get_subscriptions_reminder_due(session, days_ahead=days_ahead)
                base = (Settings().webapp_base_url or "").rstrip("/")
                pay_url = base + "/webapp/trainer-pay-subscription" if base else None
                for sub in due:
                    tid = sub.get("trainer_telegram_id")
                    if not tid:
                        continue
                    expires_at = sub.get("expires_at")
                    expires_date = expires_at.strftime("%d.%m.%Y") if hasattr(expires_at, "strftime") else str(expires_at)[:10]
                    text = msg.TRAINER_SUBSCRIPTION_REMINDER.format(expires_date=expires_date)
                    kb = None
                    if pay_url:
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_PAY_SUBSCRIPTION, url=pay_url)],
                        ])
                    try:
                        await trainer_bot.send_message(
                            chat_id=tid,
                            text=text,
                            reply_markup=kb,
                        )
                        await mark_subscription_reminder_sent(session, sub["id"])
                    except Exception as e:
                        logger.warning(
                            "Subscription reminder to trainer %s (sub id=%s): %s",
                            tid,
                            sub.get("id"),
                            e,
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Subscription expire/reminder loop: %s", e)


async def run_certificate_email_outbox_loop() -> None:
    """Every 2 min: process certificate_email_outbox (retry failed sends)."""
    while True:
        await asyncio.sleep(CERTIFICATE_OUTBOX_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                n = await process_certificate_email_outbox_batch(session, limit=20)
                if n:
                    logger.info("Certificate email outbox: %d processed", n)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Certificate email outbox loop: %s", e)
