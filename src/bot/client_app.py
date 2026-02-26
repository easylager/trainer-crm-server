"""
Client bot entry point. Public: anyone can /start and use as client.
Run: python -m src.bot.client_app
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands

from src.application.booking_use_cases import (
    get_pending_booking_cancel_notifications,
    list_bookings_to_complete,
    mark_booking_cancel_notification_sent,
    mark_booking_completed_and_notify,
)
from src.application.client_request_use_cases import (
    get_pending_response_notifications,
    mark_response_notified,
)
from src.shared.config import Settings
from src.bot import messages as msg
from src.bot.handlers.client_handlers import router as client_router
from src.infrastructure.db import async_session_factory

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

RESPONSE_NOTIFIER_INTERVAL_SEC = 20
CANCEL_NOTIFIER_INTERVAL_SEC = 15
BOOKING_COMPLETE_INTERVAL_SEC = 60  # TODO: 30 * 60 for prod; 1 min for testing


async def _booking_complete_loop(bot: Bot) -> None:
    print("[booking_complete_loop] started")
    """Mark past-slot bookings as completed; notify client with 'leave feedback' button."""
    # while True:
    #     await asyncio.sleep(BOOKING_COMPLETE_INTERVAL_SEC)
    print("[booking_complete_loop] tick")
    try:
        async with async_session_factory() as session:
            to_complete = await list_bookings_to_complete(session)
            print(f"[booking_complete_loop] found {len(to_complete)} bookings to complete")
            for b in to_complete:
                print(f"[booking_complete_loop] completing booking_id={b['id']} client_telegram_id={b.get('client_telegram_id')}")
                await mark_booking_completed_and_notify(session, b["id"])
                chat_id = b.get("client_telegram_id")
                if not chat_id:
                    print(f"[booking_complete_loop] skip booking_id={b['id']}: no client_telegram_id")
                    continue
                slot_date = b.get("slot_date")
                start_time = b.get("start_time")
                date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
                day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
                time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
                text = msg.CLIENT_BOOKING_COMPLETED.format(date=date_str, day=day_str, time=time_str)
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=msg.CLIENT_BUTTON_LEAVE_FEEDBACK,
                        callback_data=f"feedback_booking:{b['id']}",
                    )],
                ])
                try:
                    await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
                    print(f"[booking_complete_loop] sent 'completed + feedback' to client chat_id={chat_id}")
                except Exception as e:
                    logger.warning("Completed notifier send to client %s: %s", chat_id, e)
                    print(f"[booking_complete_loop] send failed chat_id={chat_id}: {e}")
    except asyncio.CancelledError:
        print("[booking_complete_loop] cancelled")
    except Exception as e:
        logger.exception("Booking complete loop: %s", e)
        print(f"[booking_complete_loop] error: {e}")


async def _cancel_notifier_loop(bot: Bot) -> None:
    """Notify clients when trainer cancelled their booking."""
    while True:
        await asyncio.sleep(CANCEL_NOTIFIER_INTERVAL_SEC)
        try:
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
            async with async_session_factory() as session:
                pending = await get_pending_response_notifications(session)
                for p in pending:
                    client_tid = p.get("client_telegram_id")
                    if not client_tid:
                        continue
                    try:
                        await bot.send_message(
                            chat_id=client_tid,
                            text=msg.CLIENT_RESPONSE_NOTIFICATION,
                        )
                    except Exception as e:
                        logger.warning("Response notifier send to client %s: %s", client_tid, e)
                    await mark_response_notified(session, p["response_id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Response notifier: %s", e)


async def setup_menu_and_commands(bot: Bot) -> None:
    """Menu button (left of attachment): opens command list. Only /settings (no /start)."""
    await bot.set_my_commands(
        [
            BotCommand(command="settings", description="Настройки выбора"),
            BotCommand(command="book", description="Записаться к выбранному тренеру"),
            BotCommand(command="request", description="Оставить заявку"),
            BotCommand(command="my_requests", description="Мои заявки и отклики"),
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
    dp.include_router(client_router)
    response_notifier = asyncio.create_task(_response_notifier_loop(bot))
    cancel_notifier = asyncio.create_task(_cancel_notifier_loop(bot))
    complete_notifier = asyncio.create_task(_booking_complete_loop(bot))
    logger.info(
        "Client bot polling started (response %ss, cancel %ss, complete %ss)",
        RESPONSE_NOTIFIER_INTERVAL_SEC,
        CANCEL_NOTIFIER_INTERVAL_SEC,
        BOOKING_COMPLETE_INTERVAL_SEC,
    )
    try:
        await dp.start_polling(bot)
    finally:
        response_notifier.cancel()
        cancel_notifier.cancel()
        complete_notifier.cancel()
        for t in (response_notifier, cancel_notifier, complete_notifier):
            try:
                await t
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
