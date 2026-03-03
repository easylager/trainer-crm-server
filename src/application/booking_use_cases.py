"""
Booking use cases: create booking (slot + client_id, comment), list for trainer, pending notifications.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.notification_hours import NOTIFICATION_TZ

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]


async def create_booking(
    session: AsyncSession,
    slot_id: int,
    trainer_id: int,
    client_id: int,
    client_comment: str | None = None,
    client_request_id: int | None = None,
    created_by_trainer: bool = False,
) -> int | None:
    """
    Create booking: insert row and set slot status to 'booked'.
    If client_request_id is set, link booking to that request and archive the request.
    When created_by_trainer=True and client_request_id is set, leave client_notified_trainer_booked_at
    null so client bot sends "trainer booked you"; when False (client booked themselves) set it to now()
    to avoid duplicate notification.
    Returns booking id or None if slot not available / wrong trainer.
    """
    r = await session.execute(
        text("""
            SELECT id FROM slots
            WHERE id = :sid AND trainer_id = :tid AND status = 'available'
        """),
        {"sid": slot_id, "tid": trainer_id},
    )
    if not r.fetchone():
        return None
    r = await session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, client_comment, client_request_id)
            VALUES (:sid, :tid, :cid, :comment, :req_id)
            RETURNING id
        """),
        {
            "sid": slot_id,
            "tid": trainer_id,
            "cid": client_id,
            "comment": (client_comment or "").strip() or None,
            "req_id": client_request_id,
        },
    )
    (booking_id,) = r.fetchone()
    await session.execute(
        text("UPDATE slots SET status = 'booked' WHERE id = :id"),
        {"id": slot_id},
    )
    if client_request_id is not None:
        await session.execute(
            text("UPDATE client_requests SET status = 'archived' WHERE id = :id"),
            {"id": client_request_id},
        )
    if client_request_id is not None and not created_by_trainer:
        await session.execute(
            text("UPDATE bookings SET client_notified_trainer_booked_at = NOW() WHERE id = :id"),
            {"id": booking_id},
        )
    await session.commit()
    return booking_id


async def generate_reminders_for_booking(session: AsyncSession, booking_id: int) -> None:
    """
    Create reminder rows for a booking according to strategy:
    - If booking created earlier than slot_date: try 24h and 2h reminders.
    - If booking created in the same day as slot: only 2h reminder, и только если осталось >2 часов.
    - Никогда не создаём напоминания в ночные часы (0–7); такие кандидаты просто пропускаем.
    """
    r = await session.execute(
        text(
            """
            SELECT b.id, c.telegram_id, b.created_at, s.slot_date, s.start_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :id
            """
        ),
        {"id": booking_id},
    )
    row = r.fetchone()
    if not row:
        return

    bid = row[0]
    client_telegram_id = row[1]
    created_at: datetime = row[2]
    slot_date = row[3]
    start_time = row[4]

    # Treat slot_date/start_time as local (Europe/Minsk) time, and compare in that timezone.
    local_tz = ZoneInfo(NOTIFICATION_TZ)
    # created_at comes from DB as UTC (timestamptz) – normalize and convert to local tz.
    if created_at.tzinfo is None:
        created_local = created_at.replace(tzinfo=timezone.utc).astimezone(local_tz)
    else:
        created_local = created_at.astimezone(local_tz)
    slot_dt_local = datetime.combine(slot_date, start_time).replace(tzinfo=local_tz)

    # If slot already started or in the past relative to creation – no reminders.
    if slot_dt_local <= created_local:
        return

    def is_quiet_hours(dt: datetime) -> bool:
        # Simple rule: 0:00–7:59 считаем ночными, туда ничего не шлём.
        return 0 <= dt.hour < 8

    reminders: list[tuple[str, datetime]] = []

    t24 = slot_dt_local - timedelta(hours=24)
    t2 = slot_dt_local - timedelta(hours=2)

    # Booking created before slot calendar day → потенциально 24h + 2h.
    if created_local.date() < slot_date:
        if t24 > created_local and t24 < slot_dt_local and not is_quiet_hours(t24):
            reminders.append(("before_24h", t24))
        if t2 > created_local and t2 < slot_dt_local and not is_quiet_hours(t2):
            reminders.append(("before_2h", t2))
    else:
        # Booking created in the same calendar day as slot.
        # Если до слота осталось больше 2 часов, создаём только 2h-напоминание.
        if created_local < t2 and t2 < slot_dt_local and not is_quiet_hours(t2):
            reminders.append(("before_2h", t2))
        # Если клиент записался позже, чем за 2 часа до начала, дополнительных напоминаний не создаём.

    for kind, send_at in reminders:
        # Store send_at in UTC so comparison with NOW() in DB is correct.
        send_at_utc = send_at.astimezone(timezone.utc)
        await session.execute(
            text(
                """
                INSERT INTO reminders (booking_id, client_telegram_id, kind, send_at, status)
                VALUES (:bid, :ctid, :kind, :send_at, 'pending')
                """
            ),
            {
                "bid": bid,
                "ctid": client_telegram_id,
                "kind": kind,
                "send_at": send_at_utc,
            },
        )
    # Напоминания можно коммитить отдельно от самой брони (create_booking уже сделал commit).
    await session.commit()


async def get_pending_trainer_booked_notifications(session: AsyncSession, limit: int = 50) -> list[dict]:
    """
    Bookings created by trainer with client_request_id, client not yet notified.
    Returns: booking_id, client_telegram_id, trainer_name, slot_date, start_time.
    """
    r = await session.execute(
        text("""
            SELECT b.id, c.telegram_id,
                   COALESCE(TRIM(CONCAT(tp.first_name, ' ', tp.last_name)), 'Тренер'),
                   s.slot_date, s.start_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE b.client_request_id IS NOT NULL
              AND b.client_notified_trainer_booked_at IS NULL
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "booking_id": row[0],
            "client_telegram_id": row[1],
            "trainer_name": (row[2] or "Тренер").strip(),
            "slot_date": row[3],
            "start_time": row[4],
        }
        for row in rows
    ]


async def mark_trainer_booked_notified(session: AsyncSession, booking_id: int) -> None:
    """Mark that we sent the client the 'trainer booked you' notification."""
    await session.execute(
        text("UPDATE bookings SET client_notified_trainer_booked_at = NOW() WHERE id = :id"),
        {"id": booking_id},
    )
    await session.commit()


async def list_pending_reminders(session: AsyncSession, limit: int = 100) -> list[dict]:
    """
    Reminders due to send: status=pending, send_at <= now.
    Only for non-cancelled bookings. Returns list of dicts with id, client_telegram_id, kind, slot_date, start_time.
    """
    r = await session.execute(
        text("""
            SELECT r.id, r.client_telegram_id, r.kind, s.slot_date, s.start_time, s.end_time
            FROM reminders r
            JOIN bookings b ON b.id = r.booking_id
            JOIN slots s ON s.id = b.slot_id
            WHERE r.status = 'pending'
              AND r.send_at <= now()
              AND b.status != 'cancelled'
            ORDER BY r.send_at
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "client_telegram_id": row[1],
            "kind": row[2],
            "slot_date": row[3],
            "start_time": row[4],
            "end_time": row[5],
        }
        for row in rows
    ]


async def mark_reminder_sent(session: AsyncSession, reminder_id: int) -> None:
    await session.execute(
        text(
            "UPDATE reminders SET status = 'sent', sent_at = now() WHERE id = :id"
        ),
        {"id": reminder_id},
    )
    await session.commit()


async def mark_reminder_failed(session: AsyncSession, reminder_id: int, error: str) -> None:
    await session.execute(
        text(
            "UPDATE reminders SET status = 'failed', error = :err WHERE id = :id"
        ),
        {"id": reminder_id, "err": (error or "")[:500]},
    )
    await session.commit()


async def get_booking_with_slot(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """Load booking by id with slot date/time and client_id; None if not found or wrong trainer."""
    r = await session.execute(
        text("""
            SELECT b.id, b.slot_id, b.client_id, c.telegram_id, c.phone, b.client_comment, b.created_at,
                   s.slot_date, s.start_time, s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :id AND b.trainer_id = :tid
        """),
        {"id": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "slot_id": row[1],
        "client_id": row[2],
        "client_telegram_id": row[3],
        "client_phone": row[4] or "",
        "client_comment": row[5],
        "created_at": row[6],
        "slot_date": row[7],
        "start_time": row[8],
        "end_time": row[9],
    }


async def list_bookings_for_trainer(
    session: AsyncSession,
    trainer_id: int,
    limit: int = 100,
) -> list[dict]:
    """
    List active upcoming bookings for trainer (slot_date >= today, slot still booked).
    Sorted nearest first (slot_date ASC, start_time ASC) so first page = today, next = tomorrow, etc.
    No past days — trainer sees only current day and future.
    """
    r = await session.execute(
        text("""
            WITH numbered AS (
                SELECT b.id, b.slot_id, b.client_id,
                       c.telegram_id, c.phone, c.first_name AS client_first_name, c.last_name AS client_last_name,
                       b.client_comment, b.created_at,
                       s.slot_date, s.start_time, s.end_time,
                       ROW_NUMBER() OVER (PARTITION BY b.trainer_id, b.client_id ORDER BY s.slot_date, s.start_time) AS session_num,
                       (SELECT string_agg(srv.name, ', ' ORDER BY srv.name)
                        FROM trainer_services ts
                        JOIN services srv ON srv.id = ts.service_id
                        WHERE ts.trainer_id = b.trainer_id) AS services_str,
                       (SELECT string_agg(a.name, ', ' ORDER BY a.name)
                        FROM trainer_arenas ta
                        JOIN arenas a ON a.id = ta.arena_id
                        WHERE ta.trainer_id = b.trainer_id) AS arenas_str
                FROM bookings b
                JOIN clients c ON c.id = b.client_id
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid AND s.status = 'booked' AND s.slot_date >= CURRENT_DATE
            )
            SELECT id, slot_id, telegram_id, phone, client_first_name, client_last_name,
                   client_comment, created_at, slot_date, start_time, end_time,
                   session_num, services_str, arenas_str
            FROM numbered
            ORDER BY slot_date ASC, start_time ASC
            LIMIT :lim
        """),
        {"tid": trainer_id, "lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "slot_id": row[1],
            "client_telegram_id": row[2],
            "client_phone": row[3] or "",
            "client_first_name": row[4],
            "client_last_name": row[5],
            "client_comment": row[6],
            "created_at": row[7],
            "slot_date": row[8],
            "start_time": row[9],
            "end_time": row[10],
            "session_num": row[11],
            "services_str": (row[12] or "").strip() or None,
            "arenas_str": (row[13] or "").strip() or None,
        }
        for row in rows
    ]


async def list_bookings_for_client(
    session: AsyncSession,
    client_telegram_id: int,
    limit: int = 50,
) -> list[dict]:
    """List client's active (upcoming) bookings only — pending, not completed/cancelled; slot still booked."""
    r = await session.execute(
        text("""
            SELECT b.id, b.slot_id, b.trainer_id, b.client_comment,
                   s.slot_date, s.start_time, s.end_time,
                   (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60)::int AS duration_minutes,
                   COALESCE(TRIM(p.first_name || ' ' || p.last_name), 'Тренер') AS trainer_name,
                   t.telegram_id AS trainer_telegram_id
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            WHERE c.telegram_id = :ctid AND s.status = 'booked' AND b.status = 'pending'
            ORDER BY s.slot_date ASC, s.start_time ASC
            LIMIT :lim
        """),
        {"ctid": client_telegram_id, "lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "slot_id": row[1],
            "trainer_id": row[2],
            "client_comment": row[3],
            "slot_date": row[4],
            "start_time": row[5],
            "end_time": row[6],
            "duration_minutes": row[7] if row[7] is not None else 45,
            "trainer_name": (row[8] or "").strip() or "Тренер",
            "trainer_telegram_id": row[9],
        }
        for row in rows
    ]


async def get_bookings_pending_notification(session: AsyncSession) -> list[dict]:
    """Bookings where notified_at is null (for trainer bot to send push)."""
    r = await session.execute(
        text("""
            SELECT b.id, b.trainer_id, b.slot_id, c.telegram_id, c.phone, b.client_comment,
                   s.slot_date, s.start_time, s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.notified_at IS NULL
            ORDER BY b.created_at ASC
        """),
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "trainer_id": row[1],
            "slot_id": row[2],
            "client_telegram_id": row[3],
            "client_phone": row[4] or "",
            "client_comment": row[5],
            "slot_date": row[6],
            "start_time": row[7],
            "end_time": row[8],
        }
        for row in rows
    ]


async def mark_booking_notified(session: AsyncSession, booking_id: int) -> None:
    await session.execute(
        text("UPDATE bookings SET notified_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": booking_id},
    )
    await session.commit()


async def cancel_booking(session: AsyncSession, booking_id: int, trainer_id: int) -> bool:
    """
    Cancel booking: set slot back to 'available', booking status to 'cancelled', cancel reminders, enqueue client notification.
    Returns True if booking was found and cancelled.
    """
    r = await session.execute(
        text("""
            UPDATE slots s
            SET status = 'available'
            FROM bookings b
            WHERE b.slot_id = s.id AND b.id = :bid AND b.trainer_id = :tid AND s.status = 'booked'
            RETURNING s.id
        """),
        {"bid": booking_id, "tid": trainer_id},
    )
    if not r.fetchone():
        return False
    await session.execute(
        text("UPDATE bookings SET status = 'cancelled' WHERE id = :bid"),
        {"bid": booking_id},
    )
    await session.execute(
        text("UPDATE reminders SET status = 'cancelled' WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    await _schedule_booking_cancel_notification(session, booking_id)
    await session.commit()
    return True


async def _schedule_booking_cancel_notification(session: AsyncSession, booking_id: int) -> None:
    """Enqueue one row for client bot to send 'trainer cancelled your booking' message."""
    await session.execute(
        text("""
            INSERT INTO booking_cancel_notifications (booking_id, client_telegram_id, slot_date, start_time, trainer_display_name)
            SELECT b.id, c.telegram_id, s.slot_date, s.start_time,
                   TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, '')))
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            WHERE b.id = :bid
            ON CONFLICT (booking_id) DO NOTHING
        """),
        {"bid": booking_id},
    )
    # No RETURNING needed; client bot will poll by sent_at IS NULL


async def get_trainer_telegram_id(session: AsyncSession, trainer_id: int) -> int | None:
    """Trainer telegram_id for sending notification."""
    r = await session.execute(
        text("SELECT telegram_id FROM trainers WHERE id = :id"),
        {"id": trainer_id},
    )
    row = r.fetchone()
    return row[0] if row and row[0] is not None else None


async def get_pending_booking_cancel_notifications(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Rows where sent_at IS NULL for client bot to send 'trainer cancelled' message."""
    r = await session.execute(
        text("""
            SELECT id, booking_id, client_telegram_id, slot_date, start_time, trainer_display_name
            FROM booking_cancel_notifications
            WHERE sent_at IS NULL
            ORDER BY created_at ASC
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "booking_id": row[1],
            "client_telegram_id": row[2],
            "slot_date": row[3],
            "start_time": row[4],
            "trainer_display_name": row[5] or "Тренер",
        }
        for row in rows
    ]


async def mark_booking_cancel_notification_sent(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        text("UPDATE booking_cancel_notifications SET sent_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": notification_id},
    )
    await session.commit()


# --- Auto-complete: mark booking completed when slot end has passed; enqueue feedback notifications ---

async def list_bookings_to_complete(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Bookings with status=pending and slot (date + end_time) already in the past."""
    r = await session.execute(
        text("""
            SELECT b.id, c.telegram_id, b.trainer_id,
                   s.slot_date, s.start_time, s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.status = 'pending' AND s.status = 'booked'
              AND (s.slot_date + s.end_time) < CURRENT_TIMESTAMP
            ORDER BY s.slot_date, s.end_time
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "client_telegram_id": row[1],
            "trainer_id": row[2],
            "slot_date": row[3],
            "start_time": row[4],
            "end_time": row[5],
        }
        for row in rows
    ]


async def mark_booking_completed_and_notify(
    session: AsyncSession,
    booking_id: int,
) -> None:
    """Set booking status to completed and insert row for trainer feedback notification."""
    await session.execute(
        text("UPDATE bookings SET status = 'completed' WHERE id = :bid"),
        {"bid": booking_id},
    )
    await session.execute(
        text("""
            INSERT INTO booking_completed_notifications (booking_id, client_telegram_id, trainer_id)
            SELECT b.id, c.telegram_id, b.trainer_id FROM bookings b
            JOIN clients c ON c.id = b.client_id WHERE b.id = :bid
            ON CONFLICT (booking_id) DO NOTHING
        """),
        {"bid": booking_id},
    )
    await session.commit()


async def get_pending_completed_for_trainer(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Rows where trainer has not yet been notified (trainer_sent_at IS NULL)."""
    r = await session.execute(
        text("""
            SELECT n.id, n.booking_id, n.trainer_id, n.client_telegram_id,
                   s.slot_date, s.start_time
            FROM booking_completed_notifications n
            JOIN bookings b ON b.id = n.booking_id
            JOIN slots s ON s.id = b.slot_id
            WHERE n.trainer_sent_at IS NULL
            ORDER BY n.id
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "booking_id": row[1],
            "trainer_id": row[2],
            "client_telegram_id": row[3],
            "slot_date": row[4],
            "start_time": row[5],
        }
        for row in rows
    ]


async def mark_trainer_completed_sent(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        text("UPDATE booking_completed_notifications SET trainer_sent_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": notification_id},
    )
    await session.commit()


async def get_booking_for_client_feedback(
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
) -> dict | None:
    """Booking by id and client; must be completed. Returns trainer_id and slot info for feedback flow."""
    r = await session.execute(
        text("""
            SELECT b.id, b.trainer_id, s.slot_date, s.start_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND c.telegram_id = :ctid AND b.status = 'completed'
        """),
        {"bid": booking_id, "ctid": client_telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {"id": row[0], "trainer_id": row[1], "slot_date": row[2], "start_time": row[3]}


async def get_completed_booking_for_repeat(
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
) -> dict | None:
    """Completed booking by id and client; for repeat/recurring flows. Returns trainer_id, client_id, slot_date, start_time, end_time."""
    r = await session.execute(
        text("""
            SELECT b.id, b.trainer_id, b.client_id, s.slot_date, s.start_time, s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND c.telegram_id = :ctid AND b.status = 'completed'
        """),
        {"bid": booking_id, "ctid": client_telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "trainer_id": row[1],
        "client_id": row[2],
        "slot_date": row[3],
        "start_time": row[4],
        "end_time": row[5],
    }


async def get_booking_for_trainer_feedback(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """Completed booking by id and trainer; for trainer to leave review. None if not found or not completed."""
    r = await session.execute(
        text("""
            SELECT b.id FROM bookings b
            WHERE b.id = :bid AND b.trainer_id = :tid AND b.status = 'completed'
        """),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {"id": row[0]}


async def set_booking_trainer_review(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
    review_text: str,
) -> bool:
    """Save trainer's optional review text for a completed booking. Returns True if updated."""
    r = await session.execute(
        text("""
            UPDATE bookings SET trainer_review_text = :text
            WHERE id = :bid AND trainer_id = :tid AND status = 'completed'
            RETURNING id
        """),
        {"bid": booking_id, "tid": trainer_id, "text": (review_text or "").strip()[:2000]},
    )
    if not r.fetchone():
        return False
    await session.commit()
    return True
