"""
Recurring client slots (fixed weekly time) and wait-for-slot requests.
Clean separation: domain rules here; booking/slot creation delegated to booking_use_cases and schedule.
"""
from datetime import date, time, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import create_booking, get_first_service_id_for_trainer
from src.application.trainer_schedule_use_cases import next_week_monday

RECURRING_STATUS_ACTIVE = "active"
RECURRING_STATUS_PAUSED = "paused"
RECURRING_STATUS_CANCELLED = "cancelled"


async def create_recurring_client_slot(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    day_of_week: int,
    start_time: time,
    end_time: time,
) -> int | None:
    """Create recurring slot. Returns id or None if active one already exists for (trainer, client, day, time)."""
    r = await session.execute(
        text("""
            SELECT id FROM recurring_client_slots
            WHERE trainer_id = :tid AND client_id = :cid AND day_of_week = :dow AND start_time = :st AND status = 'active'
        """),
        {"tid": trainer_id, "cid": client_id, "dow": day_of_week, "st": start_time},
    )
    if r.fetchone():
        return None
    r = await session.execute(
        text("""
            INSERT INTO recurring_client_slots (trainer_id, client_id, day_of_week, start_time, end_time, status)
            VALUES (:tid, :cid, :dow, :st, :et, :status)
            RETURNING id
        """),
        {
            "tid": trainer_id,
            "cid": client_id,
            "dow": day_of_week,
            "st": start_time,
            "et": end_time,
            "status": RECURRING_STATUS_ACTIVE,
        },
    )
    (pk,) = r.fetchone()
    await session.commit()
    return pk


async def cancel_recurring_client_slot(
    session: AsyncSession,
    trainer_id: int,
    recurring_id: int,
) -> bool:
    """Set status=cancelled. Returns True if updated."""
    r = await session.execute(
        text("""
            UPDATE recurring_client_slots
            SET status = :status
            WHERE id = :id AND trainer_id = :tid AND status = 'active'
            RETURNING id
        """),
        {"id": recurring_id, "tid": trainer_id, "status": RECURRING_STATUS_CANCELLED},
    )
    if r.fetchone() is None:
        return False
    await session.commit()
    return True


async def get_active_recurring_for_booking(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    day_of_week: int,
    start_time: time,
) -> dict | None:
    """Active recurring row for (trainer, client, day, time) or None."""
    r = await session.execute(
        text("""
            SELECT id, trainer_id, client_id, day_of_week, start_time, end_time
            FROM recurring_client_slots
            WHERE trainer_id = :tid AND client_id = :cid AND day_of_week = :dow AND start_time = :st AND status = 'active'
        """),
        {"tid": trainer_id, "cid": client_id, "dow": day_of_week, "st": start_time},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "trainer_id": row[1],
        "client_id": row[2],
        "day_of_week": row[3],
        "start_time": row[4],
        "end_time": row[5],
    }


async def has_other_active_recurring(
    session: AsyncSession,
    trainer_id: int,
    day_of_week: int,
    start_time: time,
    exclude_client_id: int,
) -> bool:
    """True if another client (not exclude_client_id) already has active recurring for this (trainer, day, time)."""
    r = await session.execute(
        text("""
            SELECT 1 FROM recurring_client_slots
            WHERE trainer_id = :tid AND day_of_week = :dow AND start_time = :st
              AND status = 'active' AND client_id != :exclude_cid
            LIMIT 1
        """),
        {"tid": trainer_id, "dow": day_of_week, "st": start_time, "exclude_cid": exclude_client_id},
    )
    return r.fetchone() is not None


def _slot_status_on_date(
    row: tuple | None,
) -> tuple[str | None, dict | None]:
    """From DB row: 'available' + info, 'booked' + None, or (None, None)."""
    if not row:
        return None, None
    slot_id, sdate, end_time, status = row[0], row[1], row[2], (row[3] or "").strip()
    if status == "available":
        return "available", {"slot_id": slot_id, "slot_date": sdate, "end_time": end_time}
    return "booked", None


async def get_slot_status_on_date(
    session: AsyncSession,
    trainer_id: int,
    slot_date: date,
    start_time: time,
) -> tuple[str | None, dict | None]:
    """
    Status of slot on exact date: 'available' + slot_info, 'booked' + None, or (None, None) if no slot.
    Use for "same time in N days" (e.g. booking_complete: slot_date + 7).
    """
    # Normalize to hour:minute so DB TIME matches (e.g. 10:00 vs 10:00:00.000)
    st = start_time.replace(second=0, microsecond=0) if hasattr(start_time, "replace") else start_time
    r = await session.execute(
        text("""
            SELECT id, slot_date, end_time, status
            FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND start_time = :st
        """),
        {"tid": trainer_id, "d": slot_date, "st": st},
    )
    return _slot_status_on_date(r.fetchone())


async def get_slot_status_next_week(
    session: AsyncSession,
    trainer_id: int,
    day_of_week: int,
    start_time: time,
) -> tuple[str | None, dict | None]:
    """
    Next week same (weekday, time) from today: 'available' + slot_info, 'booked' + None, or (None, None) if no slot.
    So we can tell client: free → book; booked → honest "slot taken"; no slot → add wait + "when added we'll notify".
    """
    week_start = next_week_monday()
    slot_date = week_start + timedelta(days=day_of_week)
    r = await session.execute(
        text("""
            SELECT id, slot_date, end_time, status
            FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND start_time = :st
        """),
        {"tid": trainer_id, "d": slot_date, "st": start_time},
    )
    return _slot_status_on_date(r.fetchone())


async def find_available_slot_next_week(
    session: AsyncSession,
    trainer_id: int,
    day_of_week: int,
    start_time: time,
) -> dict | None:
    """Available slot next week: same weekday and start_time. Returns slot id, slot_date, end_time or None."""
    status, slot_info = await get_slot_status_next_week(session, trainer_id, day_of_week, start_time)
    return slot_info if status == "available" else None


async def add_slot_wait_request(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    day_of_week: int,
    start_time: time,
) -> int:
    """Add wait request (notify when slot appears). Returns id."""
    r = await session.execute(
        text("""
            INSERT INTO client_slot_wait_requests (trainer_id, client_id, day_of_week, start_time)
            VALUES (:tid, :cid, :dow, :st)
            RETURNING id
        """),
        {"tid": trainer_id, "cid": client_id, "dow": day_of_week, "st": start_time},
    )
    (pk,) = r.fetchone()
    await session.commit()
    return pk


async def find_available_slot_in_week(
    session: AsyncSession,
    trainer_id: int,
    week_start: date,
    day_of_week: int,
    start_time: time,
) -> int | None:
    """Available slot in given week (week_start = Monday). Returns slot_id or None."""
    slot_date = week_start + timedelta(days=day_of_week)
    r = await session.execute(
        text("""
            SELECT id FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND start_time = :st AND status = 'available'
        """),
        {"tid": trainer_id, "d": slot_date, "st": start_time},
    )
    row = r.fetchone()
    return row[0] if row else None


async def apply_recurring_bookings_for_week(
    session: AsyncSession,
    trainer_id: int,
    week_start: date,
) -> int:
    """
    For each active recurring (trainer, client, day, time), if there is an available slot that week, create booking.
    Returns number of bookings created.
    """
    service_id = await get_first_service_id_for_trainer(session, trainer_id)
    if not service_id:
        return 0
    created = 0
    for rec in await list_active_recurring_for_trainer_week(session, trainer_id, week_start):
        slot_id = await find_available_slot_in_week(
            session, trainer_id, week_start, rec["day_of_week"], rec["start_time"]
        )
        if not slot_id:
            continue
        bid, _ = await create_booking(
            session, slot_id, trainer_id, rec["client_id"], service_id=service_id, client_comment=None, client_request_id=None
        )
        if bid:
            created += 1
    return created


async def list_active_recurring_for_trainer_week(
    session: AsyncSession,
    trainer_id: int,
    week_start: date,
) -> list[dict]:
    """Active recurring slots for trainer; used to create bookings when applying week."""
    r = await session.execute(
        text("""
            SELECT id, client_id, day_of_week, start_time, end_time
            FROM recurring_client_slots
            WHERE trainer_id = :tid AND status = 'active'
            ORDER BY day_of_week, start_time
        """),
        {"tid": trainer_id},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "client_id": row[1],
            "day_of_week": row[2],
            "start_time": row[3],
            "end_time": row[4],
        }
        for row in rows
    ]


async def list_wait_requests_with_available_slots(
    session: AsyncSession,
    from_date: date,
) -> list[dict]:
    """
    Wait requests not yet notified for which an available slot exists (slot_date = from_date + day_of_week).
    from_date should be a Monday (e.g. next_week_monday()). Returns list of {id, client_telegram_id, trainer_id, slot_id, slot_date, start_time}.
    """
    r = await session.execute(
        text("""
            SELECT w.id, w.trainer_id, w.client_id, w.day_of_week, w.start_time
            FROM client_slot_wait_requests w
            WHERE w.notified_at IS NULL
        """),
    )
    wait_rows = r.fetchall()
    out = []
    for row in wait_rows:
        wid, tid, cid, dow, st = row[0], row[1], row[2], row[3], row[4]
        slot_date = from_date + timedelta(days=dow)
        r2 = await session.execute(
            text("""
                SELECT s.id, s.slot_date, s.start_time
                FROM slots s
                WHERE s.trainer_id = :tid AND s.slot_date = :d AND s.start_time = :st AND s.status = 'available'
            """),
            {"tid": tid, "d": slot_date, "st": st},
        )
        slot_row = r2.fetchone()
        if not slot_row:
            continue
        r3 = await session.execute(
            text("SELECT telegram_id FROM clients WHERE id = :id"),
            {"id": cid},
        )
        (client_telegram_id,) = r3.fetchone()
        out.append({
            "id": wid,
            "client_telegram_id": client_telegram_id,
            "trainer_id": tid,
            "slot_id": slot_row[0],
            "slot_date": slot_row[1],
            "start_time": slot_row[2],
        })
    return out


async def mark_wait_request_notified(session: AsyncSession, wait_request_id: int) -> None:
    await session.execute(
        text("UPDATE client_slot_wait_requests SET notified_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": wait_request_id},
    )
    await session.commit()
