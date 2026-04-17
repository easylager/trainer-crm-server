"""
Trigger "booking complete" once: mark past-slot bookings completed and send Telegram
notifications to clients (client bot) and trainers (trainer bot). No waiting for loops.

Usage:
  python -m scripts.trigger_complete

  If there are no pending bookings with slot end in the past, and NOTIFY_TELEGRAM_ID
  (or admin_telegram_ids[0]) is set, creates one test booking (you as client + trainer)
  and then runs complete + notifications.

Env:
  .env (Settings): database_url, telegram_bot_token_client, telegram_bot_token_trainer
  Optional: NOTIFY_TELEGRAM_ID=123456789 — your Telegram ID (or use admin_telegram_ids)
"""
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text

from src.application.booking_use_cases import (
    get_pending_completed_for_trainer,
    get_trainer_telegram_id,
    list_bookings_to_complete,
    mark_booking_completed_and_notify,
    mark_trainer_completed_sent,
)
from src.application.client_use_cases import get_or_create_client
from src.application.recurring_use_cases import get_slot_status_on_date
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings


def _slot_display_strings(slot_date, start_time):
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
    return date_str, day_str, time_str


def _notify_telegram_id(settings: Settings) -> int | None:
    raw = os.environ.get("NOTIFY_TELEGRAM_ID")
    if raw:
        try:
            return int(raw.strip())
        except ValueError:
            pass
    ids = getattr(settings, "admin_telegram_ids", None) or []
    if ids:
        return int(ids[0]) if isinstance(ids[0], str) else ids[0]
    return None


async def ensure_test_booking(notify_tid: int) -> int | None:
    """Create trainer + client (both notify_tid), past slot, pending booking. Returns booking_id or None."""
    yesterday = date.today() - timedelta(days=1)
    start = time(13, 0)
    end = time(14, 0)
    async with async_session_factory() as session:
        client_id = await get_or_create_client(session, notify_tid)
        await session.commit()
        r = await session.execute(text("SELECT id FROM trainers WHERE telegram_id = :tid"), {"tid": notify_tid})
        row = r.fetchone()
        if row:
            trainer_id = row[0]
        else:
            r = await session.execute(
                text("INSERT INTO trainers (telegram_id, status) VALUES (:tid, 'active') RETURNING id"),
                {"tid": notify_tid},
            )
            (trainer_id,) = r.fetchone()
            await session.execute(
                text("INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'Test', 'User', 30)"),
                {"tid": trainer_id},
            )
            await session.commit()
        r = await session.execute(
            text("""
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                VALUES (:tid, :d, :start, :end, 'booked')
                RETURNING id
            """),
            {"tid": trainer_id, "d": yesterday, "start": start, "end": end},
        )
        (slot_id,) = r.fetchone()
        r = await session.execute(
            text("""
                INSERT INTO bookings (slot_id, trainer_id, client_id, status)
                VALUES (:sid, :tid, :cid, 'pending')
                RETURNING id
            """),
            {"sid": slot_id, "tid": trainer_id, "cid": client_id},
        )
        (booking_id,) = r.fetchone()
        await session.commit()
    return booking_id


async def run_once() -> None:
    settings = Settings()
    notify_tid = _notify_telegram_id(settings)

    async with async_session_factory() as session:
        to_complete = await list_bookings_to_complete(session)
    if not to_complete and notify_tid is not None:
        print(f"[trigger_complete] No bookings to complete; creating test booking for telegram_id={notify_tid}")
        await ensure_test_booking(notify_tid)
        async with async_session_factory() as session:
            to_complete = await list_bookings_to_complete(session)
    if not to_complete:
        print("[trigger_complete] No bookings to complete (no pending past-slot bookings). Set NOTIFY_TELEGRAM_ID to create one.")
        return

    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    trainer_bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        for b in to_complete:
            async with async_session_factory() as session:
                await mark_booking_completed_and_notify(session, b["id"])
            chat_id = b.get("client_telegram_id")
            if chat_id:
                date_str, day_str, time_str = _slot_display_strings(b.get("slot_date"), b.get("start_time"))
                dur_m = b.get("duration_minutes")
                if dur_m is None and b.get("start_time") and b.get("end_time"):
                    try:
                        from datetime import date as date_cls, datetime as dt_cls

                        d0 = date_cls.today()
                        delta = dt_cls.combine(d0, b["end_time"]) - dt_cls.combine(d0, b["start_time"])
                        dur_m = max(0, int(delta.total_seconds() // 60))
                    except (TypeError, ValueError):
                        dur_m = None
                text_client = msg.format_client_booking_completed_notice_html(
                    date=date_str,
                    day=day_str,
                    time=time_str,
                    duration_minutes=dur_m,
                    trainer_name=b.get("trainer_name") or "Тренер",
                    service_name=b.get("service_name"),
                )
                # Same as client_app: hide Repeat/Become regular if same day+time in 7 days is already reserved
                slot_date_val = b["slot_date"]
                target_date = (slot_date_val.date() if hasattr(slot_date_val, "date") else slot_date_val) + timedelta(days=7)
                async with async_session_factory() as check_session:
                    status_next, _ = await get_slot_status_on_date(
                        check_session, b["trainer_id"], target_date, b["start_time"]
                    )
                kb = msg.build_client_booking_completed_inline_keyboard(
                    booking_id=int(b["id"]),
                    trainer_telegram_id=b.get("trainer_telegram_id"),
                    show_repeat_row=(status_next != "booked"),
                )
                try:
                    await client_bot.send_message(chat_id=chat_id, text=text_client, reply_markup=kb)
                    print(f"[trigger_complete] Client notification sent to {chat_id} (booking_id={b['id']})")
                except Exception as e:
                    print(f"[trigger_complete] Client send failed for {chat_id}: {e}")

        async with async_session_factory() as session:
            pending = await get_pending_completed_for_trainer(session)
        for p in pending:
            trainer_tid = None
            async with async_session_factory() as session:
                trainer_tid = await get_trainer_telegram_id(session, p["trainer_id"])
            if not trainer_tid:
                async with async_session_factory() as session:
                    await mark_trainer_completed_sent(session, p["id"])
                continue
            slot_date = p.get("slot_date")
            start_time = p.get("start_time")
            date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
            day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
            time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
            end_time = p.get("end_time")
            dur_min = None
            try:
                if start_time and end_time and hasattr(start_time, "hour") and hasattr(end_time, "hour"):
                    delta = datetime.combine(date.today(), end_time) - datetime.combine(
                        date.today(), start_time
                    )
                    dm = int(delta.total_seconds() // 60)
                    dur_min = dm if dm > 0 else None
            except Exception:
                dur_min = None
            text_trainer = msg.format_trainer_booking_completed_html(
                client_name=p.get("client_name") or "Клиент",
                date=date_str,
                day=day_str,
                time=time_str,
                duration_minutes=dur_min,
                service_name=p.get("service_name"),
                price_tier_label=p.get("price_tier_label"),
                arena_display=p.get("arenas_str"),
            )
            rows_tr = [
                [InlineKeyboardButton(text=msg.TRAINER_BUTTON_LEAVE_FEEDBACK, callback_data=f"feedback_booking_trainer:{p['booking_id']}")],
            ]
            if slot_date and start_time:
                sd = slot_date.date() if hasattr(slot_date, "date") else slot_date
                target_d = sd + timedelta(days=7)
                st_norm = (
                    start_time.replace(second=0, microsecond=0)
                    if hasattr(start_time, "replace")
                    else start_time
                )
                async with async_session_factory() as chk_s:
                    status_next, _ = await get_slot_status_on_date(
                        chk_s, p["trainer_id"], target_d, st_norm
                    )
                if status_next != "booked":
                    rows_tr.append(
                        [
                            InlineKeyboardButton(
                                text=msg.TRAINER_BUTTON_BOOK_SAME_TIME_NEXT_WEEK,
                                callback_data=f"trainer_repeat_week:{p['booking_id']}",
                            ),
                        ],
                    )
            kb = InlineKeyboardMarkup(inline_keyboard=rows_tr)
            try:
                await trainer_bot.send_message(chat_id=trainer_tid, text=text_trainer, reply_markup=kb)
                print(f"[trigger_complete] Trainer notification sent to {trainer_tid} (booking_id={p['booking_id']})")
            except Exception as e:
                print(f"[trigger_complete] Trainer send failed for {trainer_tid}: {e}")
            async with async_session_factory() as session:
                await mark_trainer_completed_sent(session, p["id"])
    finally:
        await client_bot.session.close()
        await trainer_bot.session.close()

    print(f"[trigger_complete] Done at {datetime.now().isoformat()}")


def main() -> None:
    try:
        Settings().database_url
    except Exception as e:
        print(f"Config error (check .env): {e}", file=sys.stderr)
        sys.exit(1)
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
