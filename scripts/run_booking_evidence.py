"""
Evidence script: booking complete + feedback flow.

Creates test data (pending booking with slot in the past), runs complete logic,
then client/trainer feedback; verifies each step and writes evidence to log.

Run from project root:
  python -m scripts.run_booking_evidence

Uses .env (via Settings) or DATABASE_URL / database_url from environment.
"""
import asyncio
import sys
from datetime import date, datetime, timedelta, time
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.config import Settings

from sqlalchemy import text

from src.application.booking_use_cases import (
    get_booking_for_client_feedback,
    get_booking_for_trainer_feedback,
    list_bookings_to_complete,
    mark_booking_completed_and_notify,
    set_booking_trainer_review,
)
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.application.trainer_use_cases import add_trainer_rating
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory

# Fallback if admin_telegram_ids not set (no real notifications)
TEST_CLIENT_PHONE = "+375001234567"
EVIDENCE_LOG: list[str] = []


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat()}] {msg}"
    EVIDENCE_LOG.append(line)
    print(line)


async def get_or_create_test_trainer(session, telegram_id: int | None = None) -> int:
    """Get or create trainer. If telegram_id given, use trainer with that telegram_id (for real notifications)."""
    if telegram_id is not None:
        r = await session.execute(text("SELECT id FROM trainers WHERE telegram_id = :tid"), {"tid": telegram_id})
        row = r.fetchone()
        if row:
            return row[0]
        r = await session.execute(
            text("INSERT INTO trainers (telegram_id, status) VALUES (:tid, 'active') RETURNING id"),
            {"tid": telegram_id},
        )
        (tid,) = r.fetchone()
        await session.execute(
            text("""
                INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age)
                VALUES (:tid, 'Evidence', 'Trainer', 30)
            """),
            {"tid": tid},
        )
        await session.commit()
        return tid
    r = await session.execute(text("SELECT id FROM trainers LIMIT 1"))
    row = r.fetchone()
    if row:
        return row[0]
    r = await session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    (tid,) = r.fetchone()
    await session.execute(
        text("""
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age)
            VALUES (:tid, 'Evidence', 'Trainer', 30)
        """),
        {"tid": tid},
    )
    await session.commit()
    return tid


async def create_past_slot_and_booking(
    session, trainer_id: int, client_telegram_id: int
) -> tuple[int, int]:
    """Create slot (yesterday 10:00–11:00) and pending booking. Returns (slot_id, booking_id)."""
    yesterday = date.today() - timedelta(days=1)
    start = time(10, 0)
    end = time(11, 0)
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
            INSERT INTO bookings (slot_id, trainer_id, client_telegram_id, client_phone, status)
            VALUES (:sid, :tid, :ctid, :phone, 'pending')
            RETURNING id
        """),
        {
            "sid": slot_id,
            "tid": trainer_id,
            "ctid": client_telegram_id,
            "phone": TEST_CLIENT_PHONE,
        },
    )
    (booking_id,) = r.fetchone()
    await session.commit()
    return slot_id, booking_id


async def get_booking_status(session, booking_id: int) -> str | None:
    r = await session.execute(text("SELECT status FROM bookings WHERE id = :id"), {"id": booking_id})
    row = r.fetchone()
    return row[0] if row else None


async def get_notification_row(session, booking_id: int) -> dict | None:
    r = await session.execute(
        text("""
            SELECT id, booking_id, client_telegram_id, trainer_id, trainer_sent_at
            FROM booking_completed_notifications WHERE booking_id = :bid
        """),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "booking_id": row[1],
        "client_telegram_id": row[2],
        "trainer_id": row[3],
        "trainer_sent_at": str(row[4]) if row[4] else None,
    }


async def get_rating_row(session, trainer_id: int, client_telegram_id: int) -> dict | None:
    r = await session.execute(
        text("SELECT rating, review_text FROM trainer_ratings WHERE trainer_id = :tid AND client_telegram_id = :ctid"),
        {"tid": trainer_id, "ctid": client_telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {"rating": row[0], "review_text": row[1]}


async def get_booking_trainer_review(session, booking_id: int) -> str | None:
    r = await session.execute(
        text("SELECT trainer_review_text FROM bookings WHERE id = :id"),
        {"id": booking_id},
    )
    row = r.fetchone()
    return row[0] if row and row[0] else None


async def run_evidence(notify_chat_id: int | None) -> bool:
    all_ok = True
    trainer_id = None
    booking_id = None
    # Use admin id as both client and trainer for test so notifications and buttons work for you
    client_telegram_id = notify_chat_id if notify_chat_id is not None else 999999001
    print(notify_chat_id)
    print(client_telegram_id)
    async with async_session_factory() as session:
        # --- 1. Ensure test trainer (with telegram_id=notify_chat_id so you get trainer bot msg) ---
        trainer_id = await get_or_create_test_trainer(session, notify_chat_id)
        log(f"EVIDENCE step 0: trainer_id={trainer_id} (telegram_id={notify_chat_id})")

        # --- 2. Create past slot + pending booking (client = notify_chat_id so you get client bot msg) ---
        slot_id, booking_id = await create_past_slot_and_booking(session, trainer_id, client_telegram_id)
        log(f"EVIDENCE step 1: created slot_id={slot_id}, booking_id={booking_id} (slot yesterday 10:00–11:00, status=pending)")

        status_before = await get_booking_status(session, booking_id)
        log(f"EVIDENCE step 2: booking status before complete = {status_before}")
        if status_before != "pending":
            log("FAIL: expected status=pending")
            all_ok = False

    # Дадим боту-тренеру время отправить уведомление о новой записи
    await asyncio.sleep(20)

    # --- 3. Run complete logic (same as client_app loop) ---
    async with async_session_factory() as session:
        to_complete = await list_bookings_to_complete(session)
        log(f"EVIDENCE step 3: list_bookings_to_complete returned {len(to_complete)} booking(s)")
        if not to_complete:
            log("FAIL: no bookings to complete (slot must be in the past)")
            all_ok = False
        else:
            for b in to_complete:
                if b["id"] == booking_id:
                    log(f"EVIDENCE step 4: our booking_id={booking_id} is in to_complete list — OK")
                    await mark_booking_completed_and_notify(session, booking_id)
                    log("EVIDENCE step 5: mark_booking_completed_and_notify(booking_id) called")
                    break
            else:
                log("FAIL: our booking_id not in to_complete")
                all_ok = False

    # --- 4. Verify booking completed + notification row ---
    async with async_session_factory() as session:
        status_after = await get_booking_status(session, booking_id)
        log(f"EVIDENCE step 6: booking status after complete = {status_after}")
        if status_after != "completed":
            log("FAIL: expected status=completed")
            all_ok = False

        notif = await get_notification_row(session, booking_id)
        if notif:
            log(f"EVIDENCE step 7: booking_completed_notifications row exists: {notif}")
        else:
            log("FAIL: no row in booking_completed_notifications")
            all_ok = False

    # --- 4b. Send real Telegram notification to client only (trainer бот пришлёт сам) ---
    # Telegram: user must have started the client bot at least once (/start) to receive messages from it.
    if notify_chat_id is not None:
        settings = Settings()
        slot_date = date.today() - timedelta(days=1)
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        date_str = slot_date.strftime("%d.%m")
        day_str = day_names[slot_date.weekday()]
        time_str = "10:00"
        try:
            bot_client = Bot(
                token=settings.telegram_bot_token_client,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            text_client = msg.format_client_booking_completed_notice_html(
                date=date_str,
                day=day_str,
                time=time_str,
                duration_minutes=60,
                trainer_name="Тренер (тест)",
                service_name="Услуга (тест)",
            )
            kb_client = msg.build_client_booking_completed_inline_keyboard(
                webapp_base_url=(Settings().webapp_base_url or ""),
                trainer_id=trainer_id,
                booking_id=int(booking_id),
                trainer_telegram_id=None,
                show_repeat_row=False,
            )
            await bot_client.send_message(chat_id=notify_chat_id, text=text_client, reply_markup=kb_client)
            await bot_client.session.close()
            log(f"EVIDENCE step 7b: sent client-bot 'completed' to chat_id={notify_chat_id}")
        except Exception as e:
            log(f"EVIDENCE step 7b: client-bot send failed — {e}")
    else:
        log("EVIDENCE step 7b: skipped (no admin_telegram_ids)")

    # --- 5. Client feedback: rating + review_text ---
    async with async_session_factory() as session:
        booking_for_client = await get_booking_for_client_feedback(session, booking_id, client_telegram_id)
        if not booking_for_client:
            log("FAIL: get_booking_for_client_feedback returned None")
            all_ok = False
        else:
            log(f"EVIDENCE step 8: get_booking_for_client_feedback OK, trainer_id={booking_for_client['trainer_id']}")

        ok = await add_trainer_rating(
            session, trainer_id, client_telegram_id,
            rating=5,
            review_text="Evidence: отличное занятие!",
        )
        if ok:
            log("EVIDENCE step 9: add_trainer_rating(5, review_text=...) OK")
        else:
            log("FAIL: add_trainer_rating returned False")
            all_ok = False

    async with async_session_factory() as session:
        rating_row = await get_rating_row(session, trainer_id, client_telegram_id)
        if rating_row and rating_row["rating"] == 5 and rating_row["review_text"]:
            log(f"EVIDENCE step 10: trainer_ratings has rating=5, review_text={rating_row['review_text'][:50]}...")
        else:
            log(f"FAIL: trainer_ratings row = {rating_row}")
            all_ok = False

    # --- 6. Trainer feedback: trainer_review_text ---
    async with async_session_factory() as session:
        booking_for_trainer = await get_booking_for_trainer_feedback(session, booking_id, trainer_id)
        if not booking_for_trainer:
            log("FAIL: get_booking_for_trainer_feedback returned None")
            all_ok = False
        else:
            log("EVIDENCE step 11: get_booking_for_trainer_feedback OK")

        ok = await set_booking_trainer_review(
            session, booking_id, trainer_id,
            "Evidence: клиент пришёл, занятие прошло хорошо.",
        )
        if ok:
            log("EVIDENCE step 12: set_booking_trainer_review(...) OK")
        else:
            log("FAIL: set_booking_trainer_review returned False")
            all_ok = False

    async with async_session_factory() as session:
        review = await get_booking_trainer_review(session, booking_id)
        if review and "Evidence" in review:
            log(f"EVIDENCE step 13: booking.trainer_review_text = {review[:50]}...")
        else:
            log(f"FAIL: trainer_review_text = {review}")
            all_ok = False

    return all_ok


def main() -> None:
    log("=== BOOKING COMPLETE + FEEDBACK EVIDENCE RUN ===")
    try:
        settings = Settings()
        settings.database_url
    except Exception as e:
        log(f"ERROR: failed to load config (.env / DATABASE_URL): {e}")
        sys.exit(1)

    notify_chat_id = None
    ids = getattr(settings, "admin_telegram_ids", None) or []
    print(ids)
    if ids:
        notify_chat_id = int(ids[0]) if isinstance(ids[0], str) else ids[0]
        log(f"Using admin_telegram_ids[0] = {notify_chat_id} for real notifications")

    ok = asyncio.run(run_evidence(notify_chat_id))
    log("")
    if ok:
        log("=== RESULT: ALL CHECKS PASSED ===")
    else:
        log("=== RESULT: SOME CHECKS FAILED ===")

    # Write to log file
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"evidence_booking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file.write_text("\n".join(EVIDENCE_LOG), encoding="utf-8")
    print("")
    print(f"Evidence log written to: {log_file}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
