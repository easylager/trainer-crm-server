"""
Notification loops: read from DB and send Telegram messages.
Used by notification_service (standalone process). Client/trainer apps no longer run these.
"""
import asyncio
import html as html_lib
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
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
    list_bookings_pending_client_completion_push,
    list_bookings_pending_confirm_reminder,
    list_bookings_to_complete,
    list_pending_reminders,
    mark_client_booking_completion_push_sent,
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
from src.application.subscription_tier_use_cases import trainer_has_crm_access
from src.application.group_attendance_use_cases import (
    attendance_rsvp_sign,
    list_pending_attendance_prompts,
    mark_attendance_prompt_failed,
    mark_attendance_prompt_sent,
    rsvp_hmac_secret,
    sync_group_attendance_prompts,
)
from src.application.subscription_use_cases import (
    expire_subscriptions_to_past_due,
    get_subscriptions_reminder_due,
    mark_subscription_reminder_sent,
)
from src.bot import messages as msg
from src.bot.handlers.trainer_handlers import REQUEST_DECLINE_PREFIX, REQUEST_RESPOND_PREFIX
from src.bot.schedule_notifications import REQUESTS_CALLBACK
from src.bot.trainer_cancel_client_notify import send_cancel_notification_payload
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings
from src.shared.map_links import build_yandex_by_map_url
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


async def _send_client_booking_completed_push(
    client_bot: Bot,
    session: AsyncSession,
    b: dict,
) -> None:
    """
    Send completion notice; mark client_booking_completed_push_sent_at only after Telegram OK.
    No telegram_id: mark sent so we do not spin on retries.
    """
    chat_id = b.get("client_telegram_id")
    booking_id = b["id"]
    if not chat_id:
        await mark_client_booking_completion_push_sent(session, booking_id)
        return
    date_str, day_str, time_str = _slot_display_strings(
        b.get("slot_date"), b.get("start_time")
    )
    duration = _reminder_duration_minutes(b.get("start_time"), b.get("end_time"))
    text = msg.format_client_booking_completed_notice_html(
        date=date_str,
        day=day_str,
        time=time_str,
        duration_minutes=b.get("duration_minutes") if b.get("duration_minutes") is not None else duration,
        trainer_name=(b.get("trainer_name") or "Тренер"),
        service_name=b.get("service_name"),
    )
    slot_date_val = b["slot_date"]
    target_date = (
        slot_date_val.date() if hasattr(slot_date_val, "date") else slot_date_val
    ) + timedelta(days=7)
    async with async_session_factory() as check_session:
        status_next, _ = await get_slot_status_on_date(
            check_session, b["trainer_id"], target_date, b["start_time"]
        )
    kb = msg.build_client_booking_completed_inline_keyboard(
        booking_id=booking_id,
        trainer_telegram_id=b.get("trainer_telegram_id"),
        show_repeat_row=(status_next != "booked"),
    )
    try:
        await client_bot.send_message(
            chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML"
        )
        await mark_client_booking_completion_push_sent(session, booking_id)
    except Exception as e:
        logger.warning(
            "Completed notifier send to client %s (booking_id=%s): %s",
            chat_id,
            booking_id,
            e,
        )


async def process_booking_complete_round(client_bot: Bot, trainer_bot: Bot) -> None:
    """
    One pass: retry failed client completion pushes, then auto-complete past slots and notify.
    Exposed for integration tests (notification_service worker runs this in a loop).
    """
    async with async_session_factory() as session:
        pending_retry = await list_bookings_pending_client_completion_push(session)
        for b in pending_retry:
            await _send_client_booking_completed_push(client_bot, session, b)

        to_complete = await list_bookings_to_complete(session)
        if to_complete:
            logger.info(
                "booking_complete_loop: %s booking(s) to complete",
                len(to_complete),
            )
        for b in to_complete:
            pass_redeemed = await mark_booking_completed_and_notify(session, b["id"])
            if not pass_redeemed:
                no_pass_payload = await get_booking_no_pass_notify_payload(session, b["id"])
                if no_pass_payload and no_pass_payload.get("trainer_telegram_id"):
                    try:
                        text = msg.TRAINER_NO_PASS_FOR_SERVICE.format(
                            client_name=html_lib.escape(
                                (no_pass_payload.get("client_name") or "Клиент").strip() or "Клиент"
                            ),
                            date=html_lib.escape(str(no_pass_payload.get("date") or "")),
                            time=html_lib.escape(str(no_pass_payload.get("time") or "")),
                            service_name=html_lib.escape(
                                str(no_pass_payload.get("service_name") or "—").strip()
                            ),
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
            await _send_client_booking_completed_push(client_bot, session, b)


async def process_cancel_notifications_batch(client_bot: Bot, session: AsyncSession) -> None:
    pending = await get_pending_booking_cancel_notifications(session)
    for p in pending:
        await send_cancel_notification_payload(client_bot, session, p)


async def process_response_notifications_batch(client_bot: Bot, session: AsyncSession) -> None:
    pending = await get_pending_response_notifications(session)
    for p in pending:
        client_tid = p.get("client_telegram_id")
        if not client_tid:
            continue
        if p.get("trainer_comment"):
            text = msg.CLIENT_RESPONSE_NOTIFICATION_WITH_COMMENT.format(
                responder_name=html_lib.escape(str(p.get("responder_name") or "Тренер")),
                comment=html_lib.escape(str(p.get("trainer_comment") or "")),
            )
        else:
            text = msg.CLIENT_RESPONSE_NOTIFICATION
        request_id = p.get("request_id")
        kb = None
        if request_id is not None:
            base = (Settings().webapp_base_url or "").rstrip("/")
            if base.startswith("https://"):
                url = f"{base}/webapp/client-requests?request_id={request_id}"
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=msg.CLIENT_RESPONSE_BUTTON_VIEW,
                                web_app=WebAppInfo(url=url),
                            )
                        ],
                    ]
                )
            else:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=msg.CLIENT_RESPONSE_BUTTON_VIEW,
                                callback_data=f"my_request:{request_id}",
                            )
                        ],
                    ]
                )
        try:
            await client_bot.send_message(
                chat_id=client_tid, text=text, reply_markup=kb
            )
            await mark_response_notified(session, p["response_id"])
        except Exception as e:
            logger.warning(
                "Response notifier send to client %s: %s", client_tid, e
            )


async def process_request_notifications_batch(
    trainer_bot: Bot, session: AsyncSession
) -> None:
    pending = await get_pending_request_notifications(session)
    for p in pending:
        tid = p.get("trainer_telegram_id")
        if not tid:
            continue
        comment = (p.get("comment") or "").strip()
        if comment:
            text = msg.TRAINER_REQUEST_NOTIFICATION.format(
                city=html_lib.escape(str(p.get("city_name") or "")),
                service=html_lib.escape(str(p.get("service_name") or "")),
                comment=html_lib.escape(comment),
            )
        else:
            text = msg.TRAINER_REQUEST_NOTIFICATION_NO_COMMENT.format(
                city=html_lib.escape(str(p.get("city_name") or "")),
                service=html_lib.escape(str(p.get("service_name") or "")),
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
            await trainer_bot.send_message(chat_id=tid, text=text, reply_markup=kb)
            await mark_request_trainer_notified(
                session, p["request_id"], p["trainer_id"]
            )
        except Exception as e:
            logger.warning("Request notifier send to %s: %s", tid, e)


async def process_completed_feedback_batch(
    trainer_bot: Bot, session: AsyncSession
) -> None:
    pending = await get_pending_completed_for_trainer(session)
    settings = Settings()
    base = (settings.webapp_base_url or "").rstrip("/")
    webapp_https = base.startswith("https://")
    for p in pending:
        trainer_tid = await get_trainer_telegram_id(session, p["trainer_id"])
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
        end_time = p.get("end_time")
        duration_done = _reminder_duration_minutes(start_time, end_time)
        text = msg.format_trainer_booking_completed_html(
            client_name=p.get("client_name") or "Клиент",
            date=date_str,
            day=day_str,
            time=time_str,
            duration_minutes=duration_done,
            service_name=p.get("service_name"),
            price_tier_label=p.get("price_tier_label"),
            arena_display=p.get("arenas_str"),
        )
        rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_LEAVE_FEEDBACK,
                    callback_data=f"feedback_booking_trainer:{p['booking_id']}",
                ),
            ],
        ]
        if p.get("client_telegram_id"):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                        url=f"tg://user?id={int(p['client_telegram_id'])}",
                    ),
                ],
            )
        if slot_date and start_time:
            sd = (
                slot_date.date() if hasattr(slot_date, "date") else slot_date
            )
            target_d = sd + timedelta(days=7)
            st_norm = (
                start_time.replace(second=0, microsecond=0)
                if hasattr(start_time, "replace")
                else start_time
            )
            status_next, _ = await get_slot_status_on_date(
                session, p["trainer_id"], target_d, st_norm
            )
            if status_next != "booked":
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_BOOK_SAME_TIME_NEXT_WEEK,
                            callback_data=f"trainer_repeat_week:{p['booking_id']}",
                        ),
                    ],
                )
        client_id = p.get("client_id")
        if (
            webapp_https
            and client_id is not None
            and await trainer_has_crm_access(session, p["trainer_id"])
        ):
            # One button per row: full labels on narrow screens.
            rows.append(
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BUTTON_CLIENT_CARD_WEBAPP,
                        web_app=WebAppInfo(
                            url=f"{base}/webapp/trainer-clients?client_id={int(client_id)}"
                        ),
                    ),
                ],
            )
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        try:
            await trainer_bot.send_message(
                chat_id=trainer_tid, text=text, reply_markup=kb
            )
            await mark_trainer_completed_sent(session, p["id"])
        except Exception as e:
            logger.warning(
                "Completed feedback send to trainer %s: %s",
                trainer_tid,
                e,
            )


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
                    text = msg.format_client_booking_reminder_text(
                        is_soon=(kind != "before_24h"),
                        date=date_str,
                        day=day_str,
                        time=time_str,
                        duration=duration,
                        service_name=p.get("service_name"),
                        booking_price_cents=p.get("booking_price_cents"),
                        arena_name=p.get("arena_name"),
                        arena_address=p.get("arena_address"),
                    )
                    arena_payload = {
                        "latitude": p.get("arena_latitude"),
                        "longitude": p.get("arena_longitude"),
                        "address": p.get("arena_address"),
                    }
                    map_url = build_yandex_by_map_url(arena_payload)
                    row: list[InlineKeyboardButton] = []
                    if p.get("trainer_telegram_id"):
                        row.append(
                            InlineKeyboardButton(
                                text=msg.CLIENT_REMINDER_BTN_WRITE_TRAINER,
                                url=f"tg://user?id={int(p['trainer_telegram_id'])}",
                            )
                        )
                    if map_url:
                        row.append(
                            InlineKeyboardButton(
                                text=msg.CLIENT_REMINDER_BTN_SHOW_ON_MAP,
                                url=map_url,
                            )
                        )
                    kb = InlineKeyboardMarkup(inline_keyboard=[row]) if row else None
                    try:
                        await client_bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=kb,
                        )
                        await mark_reminder_sent(session, p["id"])
                    except Exception as e:
                        logger.warning("Reminder send to client %s (reminder_id=%s): %s", chat_id, p["id"], e)
                        await mark_reminder_failed(session, p["id"], str(e))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Reminder loop: %s", e)


async def run_group_attendance_prompt_loop(client_bot: Bot) -> None:
    """RSVP for cohort slots: sync prompt rows, send Telegram with inline buttons."""
    while True:
        await asyncio.sleep(REMINDER_INTERVAL_SEC)
        try:
            settings = Settings()
            hours = settings.group_attendance_prompt_hours
            if not hours or int(hours) <= 0:
                continue
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                await sync_group_attendance_prompts(session, int(hours))
            async with async_session_factory() as session:
                pending = await list_pending_attendance_prompts(session, limit=40)
            secret = rsvp_hmac_secret(settings.telegram_bot_token_client)
            for p in pending:
                chat_id = p.get("client_telegram_id")
                if not chat_id:
                    continue
                date_str, day_str, time_str = _slot_display_strings(
                    p.get("slot_date"), p.get("start_time")
                )
                duration = _reminder_duration_minutes(p.get("start_time"), p.get("end_time"))
                pid = int(p["id"])
                sig_y = attendance_rsvp_sign(pid, "y", secret)
                sig_n = attendance_rsvp_sign(pid, "n", secret)
                text = msg.CLIENT_GROUP_RSVP_INVITE.format(
                    group=html_lib.escape(p.get("group_name") or "Группа"),
                    date=date_str,
                    day=day_str,
                    time=time_str,
                    duration=duration,
                )
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=msg.GROUP_RSVP_BUTTON_YES,
                                callback_data=f"RSY:{pid}:{sig_y}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=msg.GROUP_RSVP_BUTTON_NO,
                                callback_data=f"RSN:{pid}:{sig_n}",
                            )
                        ],
                    ]
                )
                try:
                    await client_bot.send_message(
                        chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML"
                    )
                    async with async_session_factory() as session:
                        await mark_attendance_prompt_sent(session, pid)
                except Exception as e:
                    logger.warning(
                        "Group RSVP send to client %s (prompt_id=%s): %s",
                        chat_id,
                        pid,
                        e,
                    )
                    async with async_session_factory() as session:
                        await mark_attendance_prompt_failed(session, pid, str(e))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Group attendance prompt loop: %s", e)


async def run_booking_complete_loop(client_bot: Bot, trainer_bot: Bot) -> None:
    logger.info("[booking_complete_loop] started")
    while True:
        try:
            await asyncio.sleep(BOOKING_COMPLETE_INTERVAL_SEC)
            if not is_within_notification_hours():
                continue
            await process_booking_complete_round(client_bot, trainer_bot)
        except asyncio.CancelledError:
            logger.info("[booking_complete_loop] cancelled")
            break
        except Exception as e:
            logger.exception("Booking complete loop: %s", e)


async def run_cancel_notifier_loop(client_bot: Bot) -> None:
    """Drain booking_cancel_notifications queue (retry if immediate send after cancel failed)."""
    while True:
        await asyncio.sleep(CANCEL_NOTIFIER_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                await process_cancel_notifications_batch(client_bot, session)
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
                await process_response_notifications_batch(client_bot, session)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Response notifier: %s", e)


async def run_no_response_reminder_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(NO_RESPONSE_REMINDER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_pending_no_response_reminders(session)
                for p in pending:
                    client_tid = p.get("client_telegram_id")
                    if not client_tid:
                        continue
                    try:
                        settings_nr = Settings()
                        kb_nr = msg.build_client_no_response_catalog_keyboard(
                            webapp_base_url=settings_nr.webapp_base_url,
                        )
                        await client_bot.send_message(
                            chat_id=client_tid,
                            text=msg.CLIENT_NO_RESPONSE_REMINDER,
                            reply_markup=kb_nr,
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
                settings_tb = Settings()
                for p in pending:
                    chat_id = p.get("client_telegram_id")
                    if not chat_id:
                        continue
                    date_str, day_str, time_str = _slot_display_strings(
                        p.get("slot_date"), p.get("start_time")
                    )
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
                    )
                    kb = msg.build_client_trainer_booked_you_inline_keyboard(
                        booking_id=int(p["booking_id"]),
                        map_url=p.get("map_link"),
                        webapp_base_url=settings_tb.webapp_base_url,
                    )
                    try:
                        await client_bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
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
                    settings_ia = Settings()
                    base_ia = (settings_ia.webapp_base_url or "").rstrip("/")
                    if base_ia.lower().startswith("https://"):
                        inactive_label = (
                            msg.CLIENT_INACTIVE_BTN_BOOK_NOW
                            if kind == INACTIVE_KIND_10_DAYS
                            else msg.CLIENT_BUTTON_OPEN_CATALOG_WEBAPP
                        )
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=inactive_label,
                                        web_app=WebAppInfo(url=f"{base_ia}/webapp/catalog"),
                                    ),
                                ],
                            ]
                        )
                    else:
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=msg.CLIENT_BUTTON_BOOK,
                                        callback_data="catalog",
                                    )
                                ],
                            ]
                        )
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
                    duration = _reminder_duration_minutes(
                        b.get("start_time"), b.get("end_time")
                    )
                    phone = b.get("client_phone") or "—"
                    comment = (b.get("client_comment") or "").strip()
                    client_name = b.get("client_name") or "Клиент"
                    service = b.get("service_name") or "—"
                    city = b.get("city_name") or "—"
                    arenas = b.get("arenas_str") or "—"
                    if comment:
                        text = msg.TRAINER_BOOKING_NOTIFICATION.format(
                            date=html_lib.escape(date_str),
                            day=html_lib.escape(dow),
                            time=html_lib.escape(time_str),
                            duration=duration,
                            client_name=html_lib.escape(client_name),
                            phone=html_lib.escape(phone),
                            service=html_lib.escape(service),
                            city=html_lib.escape(city),
                            arenas=html_lib.escape(arenas),
                            comment=html_lib.escape(comment),
                        )
                    else:
                        text = msg.TRAINER_BOOKING_NOTIFICATION_NO_COMMENT.format(
                            date=html_lib.escape(date_str),
                            day=html_lib.escape(dow),
                            time=html_lib.escape(time_str),
                            duration=duration,
                            client_name=html_lib.escape(client_name),
                            phone=html_lib.escape(phone),
                            service=html_lib.escape(service),
                            city=html_lib.escape(city),
                            arenas=html_lib.escape(arenas),
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
                    try:
                        await trainer_bot.send_message(
                            chat_id=trainer_tid, text=text, reply_markup=kb
                        )
                        await mark_booking_notified(session, b["id"])
                    except Exception as e:
                        logger.warning(
                            "Booking notifier send to trainer %s (booking_id=%s): %s",
                            trainer_tid,
                            b.get("id"),
                            e,
                        )

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
                    cn_rem = (r.get("client_name") or "").strip()
                    ph_rem = (r.get("client_phone") or "").strip()
                    if cn_rem and ph_rem:
                        client_display = f"{cn_rem} ({ph_rem})"
                    elif cn_rem:
                        client_display = cn_rem
                    else:
                        client_display = ph_rem or "клиент"
                    text2 = msg.TRAINER_BOOKING_CONFIRM_REMINDER.format(
                        client_display=html_lib.escape(str(client_display)),
                        date=html_lib.escape(date_str2),
                        day=html_lib.escape(dow2),
                        time=html_lib.escape(time_str2),
                    )
                    row_confirm = [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BOOKINGS_BUTTON_CONFIRM,
                            callback_data=f"confirm_booking:{r['booking_id']}",
                        ),
                        InlineKeyboardButton(
                            text=msg.TRAINER_BOOKINGS_BUTTON_DECLINE,
                            callback_data=f"decline_booking:{r['booking_id']}",
                        ),
                    ]
                    rows2: list[list[InlineKeyboardButton]] = [row_confirm]
                    ctid_rem = r.get("client_telegram_id")
                    if ctid_rem:
                        rows2.append(
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                                    url=f"tg://user?id={int(ctid_rem)}",
                                ),
                            ],
                        )
                    kb2 = InlineKeyboardMarkup(inline_keyboard=rows2)
                    try:
                        await trainer_bot.send_message(
                            chat_id=trainer_tid, text=text2, reply_markup=kb2
                        )
                        await mark_confirm_reminder_sent(session, r["booking_id"])
                    except Exception as e:
                        logger.warning(
                            "Confirm reminder send to trainer %s (booking_id=%s): %s",
                            trainer_tid,
                            r.get("booking_id"),
                            e,
                        )
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
                await process_request_notifications_batch(trainer_bot, session)
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
                await process_completed_feedback_batch(trainer_bot, session)
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
                    daily_kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BUTTON_REQUESTS,
                                    callback_data=REQUESTS_CALLBACK,
                                ),
                            ],
                        ]
                    )
                    try:
                        await trainer_bot.send_message(
                            chat_id=tid, text=text, reply_markup=daily_kb
                        )
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
                tariffs_url = base + "/webapp/trainer-subscription?v=20260450" if base else None
                for sub in due:
                    tid = sub.get("trainer_telegram_id")
                    if not tid:
                        continue
                    expires_at = sub.get("expires_at")
                    expires_date = expires_at.strftime("%d.%m.%Y") if hasattr(expires_at, "strftime") else str(expires_at)[:10]
                    if sub.get("status") == "trial":
                        text = msg.TRAINER_SUBSCRIPTION_REMINDER_TRIAL.format(expires_date=expires_date)
                    else:
                        text = msg.TRAINER_SUBSCRIPTION_REMINDER.format(expires_date=expires_date)
                    kb = None
                    if pay_url and tariffs_url and base.lower().startswith("https://"):
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=msg.TRAINER_SUBSCRIPTION_PUSH_BTN_PAY_NOW,
                                        url=pay_url,
                                    ),
                                    InlineKeyboardButton(
                                        text=msg.TRAINER_SUBSCRIPTION_PUSH_BTN_TARIFFS,
                                        url=tariffs_url,
                                    ),
                                ],
                            ]
                        )
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
