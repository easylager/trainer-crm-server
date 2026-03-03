"""
Trainer bot entry point. Entry only via paid link from site (t.me/bot?start=link_<token>).
Run: python -m src.bot.trainer_app
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands

from src.application.booking_use_cases import (
    get_bookings_pending_notification,
    get_pending_completed_for_trainer,
    get_trainer_telegram_id,
    mark_booking_notified,
    mark_trainer_completed_sent,
)
from src.application.client_request_use_cases import (
    get_pending_request_notifications,
    get_trainers_for_daily_request_reminder,
    mark_request_trainer_notified,
    mark_trainer_daily_request_reminder_sent,
)
from src.bot import messages as msg
from src.bot.schedule_notifications import set_client_bot
from src.bot.handlers.trainer_handlers import (
    REQUEST_BOOK_CLIENT_PREFIX,
    REQUEST_DECLINE_PREFIX,
    REQUESTS_CALLBACK,
    REQUEST_RESPOND_PREFIX,
    router as trainer_router,
)
from src.bot.middlewares.rate_limit_middleware import RateLimitMiddleware
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings
from src.shared.notification_hours import is_within_notification_hours
from src.shared.rate_limit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

BOOKING_NOTIFIER_INTERVAL_SEC = 15
REQUEST_NOTIFIER_INTERVAL_SEC = 20
COMPLETED_FEEDBACK_INTERVAL_SEC = 20
DAILY_REQUEST_REMINDER_INTERVAL_SEC = 3 * 24 * 60 * 60  # once per 2 days


def _requests_word(n: int) -> str:
    """Russian plural: 1 заявка, 2 заявки, 5 заявок."""
    if n % 10 == 1 and n % 100 != 11:
        return "заявка"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "заявки"
    return "заявок"


async def _completed_feedback_loop(bot: Bot) -> None:
    """Notify trainers about completed bookings with 'leave feedback' button."""
    while True:
        await asyncio.sleep(COMPLETED_FEEDBACK_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_pending_completed_for_trainer(session)
                for p in pending:
                    trainer_tid = await get_trainer_telegram_id(session, p["trainer_id"])
                    if not trainer_tid:
                        await mark_trainer_completed_sent(session, p["id"])
                        continue
                    slot_date = p.get("slot_date")
                    start_time = p.get("start_time")
                    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
                    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
                    time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
                    text = msg.TRAINER_BOOKING_COMPLETED.format(date=date_str, day=day_str, time=time_str)
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_LEAVE_FEEDBACK,
                            callback_data=f"feedback_booking_trainer:{p['booking_id']}",
                        )],
                    ])
                    try:
                        await bot.send_message(chat_id=trainer_tid, text=text, reply_markup=kb)
                    except Exception as e:
                        logger.warning("Completed feedback send to trainer %s: %s", trainer_tid, e)
                    await mark_trainer_completed_sent(session, p["id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Completed feedback loop: %s", e)


async def _booking_notifier_loop(bot: Bot) -> None:
    """Poll pending bookings and send notification to trainer with link to write to client."""
    while True:
        await asyncio.sleep(BOOKING_NOTIFIER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_bookings_pending_notification(session)
                for b in pending:
                    trainer_tid = await get_trainer_telegram_id(session, b["trainer_id"])
                    if not trainer_tid:
                        await mark_booking_notified(session, b["id"])
                        continue
                    d = b["slot_date"]
                    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
                    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
                    time_str = f"{b['start_time'].strftime('%H:%M') if hasattr(b['start_time'], 'strftime') else b['start_time']}–{b['end_time'].strftime('%H:%M') if hasattr(b['end_time'], 'strftime') else b['end_time']}"
                    phone = b.get("client_phone") or "—"
                    comment = (b.get("client_comment") or "").strip()
                    if comment:
                        text = msg.TRAINER_BOOKING_NOTIFICATION.format(
                            date=date_str, day=dow, time=time_str, phone=phone, comment=comment
                        )
                    else:
                        text = msg.TRAINER_BOOKING_NOTIFICATION_NO_COMMENT.format(
                            date=date_str, day=dow, time=time_str, phone=phone
                        )
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=msg.TRAINER_BOOKINGS_BUTTON_WRITE,
                            url=f"tg://user?id={b['client_telegram_id']}",
                        )],
                    ])
                    await bot.send_message(chat_id=trainer_tid, text=text, reply_markup=kb)
                    await mark_booking_notified(session, b["id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Booking notifier: %s", e)


async def _request_notifier_loop(bot: Bot) -> None:
    """Notify trainers about new client requests (matching city+service)."""
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
                    kb = InlineKeyboardMarkup(inline_keyboard=[
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
                    ])
                    try:
                        await bot.send_message(chat_id=tid, text=text, reply_markup=kb)
                    except Exception as e:
                        logger.warning("Request notifier send to %s: %s", tid, e)
                    await mark_request_trainer_notified(
                        session, p["request_id"], p["trainer_id"]
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Request notifier: %s", e)


async def _daily_request_reminder_loop(bot: Bot) -> None:
    """Once per day: notify trainers how many open requests match their city+service."""
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
                        await bot.send_message(chat_id=tid, text=text)
                        await mark_trainer_daily_request_reminder_sent(session, p["trainer_id"])
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


async def setup_menu_and_commands(bot: Bot) -> None:
    """Menu button (left of attachment): opens command list."""
    await bot.set_my_commands(
        [
            BotCommand(command="guide", description="Инструкция"),
            BotCommand(command="editor", description="Редактор расписания"),
            BotCommand(command="schedule", description="Мое расписание"),
            BotCommand(command="requests", description="Заявки клиентов"),
            BotCommand(command="bookings", description="Мои записи"),
            BotCommand(command="stats", description="Статистика"),
        ]
    )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Trainer bot: menu button and commands set")


async def main() -> None:
    settings = Settings()
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    set_client_bot(client_bot)
    await setup_menu_and_commands(bot)
    dp = Dispatcher()
    limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_sec=settings.rate_limit_window_sec,
    )
    dp.update.outer_middleware(RateLimitMiddleware(limiter, bot))
    dp.include_router(trainer_router)
    booking_notifier = asyncio.create_task(_booking_notifier_loop(bot))
    request_notifier = asyncio.create_task(_request_notifier_loop(bot))
    completed_feedback = asyncio.create_task(_completed_feedback_loop(bot))
    daily_reminder = asyncio.create_task(_daily_request_reminder_loop(bot))
    logger.info(
        "Trainer bot polling started (booking %ss, request %ss, completed %ss, daily %ss)",
        BOOKING_NOTIFIER_INTERVAL_SEC,
        REQUEST_NOTIFIER_INTERVAL_SEC,
        COMPLETED_FEEDBACK_INTERVAL_SEC,
        DAILY_REQUEST_REMINDER_INTERVAL_SEC,
    )
    try:
        await dp.start_polling(bot)
    finally:
        set_client_bot(None)
        await client_bot.session.close()
        booking_notifier.cancel()
        request_notifier.cancel()
        completed_feedback.cancel()
        daily_reminder.cancel()
        for t in (booking_notifier, request_notifier, completed_feedback, daily_reminder):
            try:
                await t
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
