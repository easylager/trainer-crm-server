"""
Client bot entry point. Public: anyone can /start and use as client.
Run: python -m src.bot.client_app
"""
import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands

from src.application.booking_use_cases import (
    get_pending_booking_cancel_notifications,
    get_pending_trainer_booked_notifications,
    list_bookings_to_complete,
    list_pending_reminders,
    mark_booking_cancel_notification_sent,
    mark_booking_completed_and_notify,
    mark_reminder_failed,
    mark_reminder_sent,
    mark_trainer_booked_notified,
)
from src.application.client_request_use_cases import (
    get_pending_no_response_reminders,
    get_pending_response_notifications,
    mark_no_response_reminder_sent,
    mark_response_notified,
)
from src.application.recurring_use_cases import get_slot_status_on_date
from src.shared.config import Settings
from src.bot import messages as msg
from src.bot.handlers.client_handlers import router as client_router
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.infrastructure.db import async_session_factory
from src.shared.notification_hours import is_within_notification_hours
from src.shared.rate_limit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

RESPONSE_NOTIFIER_INTERVAL_SEC = 20
CANCEL_NOTIFIER_INTERVAL_SEC = 15
BOOKING_COMPLETE_INTERVAL_SEC = 30 * 60  # 30 min; for testing set lower (e.g. 60)
REMINDER_INTERVAL_SEC = 60  # poll reminders every minute
NO_RESPONSE_REMINDER_INTERVAL_SEC = 60 * 1  # 1 hour; remind client if no responses after 2 days
TRAINER_BOOKED_NOTIFIER_INTERVAL_SEC = 30  # notify client when trainer booked them from request


def _slot_display_strings(slot_date, start_time):
    """Shared formatting for slot date/day/time in notifications."""
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
    return date_str, day_str, time_str


def _reminder_duration_minutes(start_time, end_time) -> int:
    """Duration in minutes from slot start/end for reminder message."""
    try:
        if start_time and end_time and hasattr(start_time, "hour") and hasattr(end_time, "hour"):
            delta = datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
            return max(0, int(delta.total_seconds() // 60))
    except (TypeError, ValueError):
        pass
    return 45


async def _reminder_loop(bot: Bot) -> None:
    """Send due reminders (24h / 2h before slot) to clients."""
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
                        text = msg.CLIENT_REMINDER_24H.format(date=date_str, day=day_str, time=time_str, duration=duration)
                    else:
                        text = msg.CLIENT_REMINDER_2H.format(date=date_str, day=day_str, time=time_str, duration=duration)
                    try:
                        await bot.send_message(chat_id=chat_id, text=text)
                        await mark_reminder_sent(session, p["id"])
                    except Exception as e:
                        logger.warning("Reminder send to client %s (reminder_id=%s): %s", chat_id, p["id"], e)
                        await mark_reminder_failed(session, p["id"], str(e))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Reminder loop: %s", e)


async def _booking_complete_loop(bot: Bot) -> None:
    """Mark past-slot bookings as completed; notify client with 'leave feedback' button. Runs every BOOKING_COMPLETE_INTERVAL_SEC."""
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
                    await mark_booking_completed_and_notify(session, b["id"])
                    chat_id = b.get("client_telegram_id")
                    if not chat_id:
                        continue
                    date_str, day_str, time_str = _slot_display_strings(
                        b.get("slot_date"), b.get("start_time")
                    )
                    text = msg.CLIENT_BOOKING_COMPLETED.format(date=date_str, day=day_str, time=time_str)
                    # Hide Repeat/Become regular if same day+time in 7 days is already reserved (fresh session to see latest slots)
                    slot_date_val = b["slot_date"]
                    target_date = (slot_date_val.date() if hasattr(slot_date_val, "date") else slot_date_val) + timedelta(days=7)
                    async with async_session_factory() as check_session:
                        status_next, _ = await get_slot_status_on_date(
                            check_session, b["trainer_id"], target_date, b["start_time"]
                        )
                    logger.info(
                        "booking_complete buttons: booking_id=%s trainer_id=%s target_date=%s start_time=%s => status=%s show_repeat_buttons=%s",
                        b["id"], b["trainer_id"], target_date, b["start_time"], status_next, status_next != "booked",
                    )
                    rows = [
                        [InlineKeyboardButton(
                            text=msg.CLIENT_BUTTON_LEAVE_FEEDBACK,
                            callback_data=f"feedback_booking:{b['id']}",
                        )],
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
                        await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
                    except Exception as e:
                        logger.warning("Completed notifier send to client %s: %s", chat_id, e)
        except asyncio.CancelledError:
            logger.info("[booking_complete_loop] cancelled")
            break
        except Exception as e:
            logger.exception("Booking complete loop: %s", e)


async def _cancel_notifier_loop(bot: Bot) -> None:
    """Notify clients when trainer cancelled their booking."""
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
                    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
                    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
                    time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
                    try:
                        text = msg.CLIENT_BOOKING_CANCELLED_BY_TRAINER.format(
                            date=date_str, day=day_str, time=time_str
                        )
                        await bot.send_message(chat_id=chat_id, text=text)
                    except Exception as e:
                        logger.warning("Cancel notifier send to client %s: %s", chat_id, e)
                    await mark_booking_cancel_notification_sent(session, p["id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Cancel notifier: %s", e)


async def _response_notifier_loop(bot: Bot) -> None:
    """Notify clients when a trainer responded to their request."""
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
                    comment = p.get("trainer_comment")
                    if comment:
                        text = msg.CLIENT_RESPONSE_NOTIFICATION_WITH_COMMENT.format(
                            responder_name=p.get("responder_name") or "Тренер",
                            comment=comment,
                        )
                    else:
                        text = msg.CLIENT_RESPONSE_NOTIFICATION
                    request_id = p.get("request_id")
                    kb = None
                    if request_id is not None:
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text=msg.CLIENT_RESPONSE_BUTTON_VIEW,
                                callback_data=f"my_request:{request_id}",
                            )],
                        ])
                    try:
                        await bot.send_message(
                            chat_id=client_tid,
                            text=text,
                            reply_markup=kb,
                        )
                    except Exception as e:
                        logger.warning("Response notifier send to client %s: %s", client_tid, e)
                    await mark_response_notified(session, p["response_id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Response notifier: %s", e)


async def _no_response_reminder_loop(bot: Bot) -> None:
    """Notify clients whose request has no responses after 2 days (once per request)."""
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
                        await bot.send_message(
                            chat_id=client_tid,
                            text=msg.CLIENT_NO_RESPONSE_REMINDER,
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


async def _trainer_booked_notifier_loop(bot: Bot) -> None:
    """Notify clients when trainer booked them from a request (created_by_trainer + client_request_id)."""
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
                        await bot.send_message(chat_id=chat_id, text=text)
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


async def setup_menu_and_commands(bot: Bot) -> None:
    """Menu button (left of attachment): opens command list. Only /settings (no /start)."""
    await bot.set_my_commands(
        [
            BotCommand(command="guide", description="Инструкция"),
            BotCommand(command="settings", description="Выбор тренера"),
            BotCommand(command="book", description="Записаться к выбранному тренеру"),
            BotCommand(command="request", description="Оставить заявку"),
            BotCommand(command="my_requests", description="Мои заявки и отклики"),
            BotCommand(command="my_bookings", description="Мои записи"),
        ]
    )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Menu button and commands set")


async def main() -> None:
    settings = Settings()
    bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await setup_menu_and_commands(bot)
    dp = Dispatcher()
    limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_sec=settings.rate_limit_window_sec,
    )
    dp.update.outer_middleware(RateLimitMiddleware(limiter, bot))
    dp.include_router(client_router)
    response_notifier = asyncio.create_task(_response_notifier_loop(bot))
    cancel_notifier = asyncio.create_task(_cancel_notifier_loop(bot))
    complete_notifier = asyncio.create_task(_booking_complete_loop(bot))
    reminder_loop_task = asyncio.create_task(_reminder_loop(bot))
    no_response_reminder_task = asyncio.create_task(_no_response_reminder_loop(bot))
    trainer_booked_task = asyncio.create_task(_trainer_booked_notifier_loop(bot))
    logger.info(
        "Client bot polling started (response %ss, cancel %ss, complete %ss, reminder %ss, no_response %ss, trainer_booked %ss)",
        RESPONSE_NOTIFIER_INTERVAL_SEC,
        CANCEL_NOTIFIER_INTERVAL_SEC,
        BOOKING_COMPLETE_INTERVAL_SEC,
        REMINDER_INTERVAL_SEC,
        NO_RESPONSE_REMINDER_INTERVAL_SEC,
        TRAINER_BOOKED_NOTIFIER_INTERVAL_SEC,
    )
    try:
        await dp.start_polling(bot)
    finally:
        response_notifier.cancel()
        cancel_notifier.cancel()
        complete_notifier.cancel()
        reminder_loop_task.cancel()
        no_response_reminder_task.cancel()
        trainer_booked_task.cancel()
        for t in (
            response_notifier,
            cancel_notifier,
            complete_notifier,
            reminder_loop_task,
            no_response_reminder_task,
            trainer_booked_task,
        ):
            try:
                await t
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
