"""
Recurring client slots (fixed weekly time) and wait-for-slot requests.
Clean separation: domain rules here; booking/slot creation delegated to booking_use_cases and schedule.
"""
from datetime import date, time, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    create_booking,
    get_first_service_id_for_trainer,
    is_slot_start_in_past_local,
)
from src.application.trainer_schedule_use_cases import next_week_monday, this_week_monday

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
              AND status <> 'cancelled'
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
              AND status <> 'cancelled'
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


async def trainer_calendar_interval_clear(
    session: AsyncSession,
    trainer_id: int,
    slot_date: date,
    interval_start: time,
    interval_end: time,
) -> bool:
    """
    True when no non-cancelled slot overlaps [interval_start, interval_end) on that day.
    Used for «repeat same time»: calendar gap without a matching slot row.
    """
    ist = (
        interval_start.replace(second=0, microsecond=0)
        if hasattr(interval_start, "replace")
        else interval_start
    )
    ien = interval_end.replace(second=0, microsecond=0) if hasattr(interval_end, "replace") else interval_end
    r = await session.execute(
        text("""
            SELECT 1 FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status <> 'cancelled'
              AND start_time < :ien AND end_time > :ist
            LIMIT 1
        """),
        {"tid": trainer_id, "d": slot_date, "ist": ist, "ien": ien},
    )
    return r.fetchone() is None


async def try_insert_client_repeat_gap_notification(
    session: AsyncSession,
    booking_id: int,
    target_slot_date: date,
) -> bool:
    """
    Idempotent trainer ping for repeat-without-slot flow.
    Returns True if this call inserted the first row for (booking, target date).

    Sandbox bookings are silently skipped: a demo identity must never pin trainers' bot with a
    «client wants to repeat» nudge. In practice sandbox clients have no telegram_id, so this is a
    belt-and-suspenders guard.
    """
    r_sb = await session.execute(
        text("SELECT is_sandbox FROM bookings WHERE id = :bid"),
        {"bid": booking_id},
    )
    row_sb = r_sb.fetchone()
    if row_sb and bool(row_sb[0]):
        return False

    r = await session.execute(
        text("""
            INSERT INTO client_repeat_gap_notifications (booking_id, target_slot_date)
            VALUES (:bid, :d)
            ON CONFLICT (booking_id, target_slot_date) DO NOTHING
            RETURNING id
        """),
        {"bid": booking_id, "d": target_slot_date},
    )
    inserted = r.fetchone() is not None
    await session.commit()
    return inserted


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


def week_monday_containing(d: date) -> date:
    """ISO week: Monday 00:00 boundary (Python weekday: Mon=0)."""
    return d - timedelta(days=d.weekday())


async def record_recurring_materialization_week_skip(
    session: AsyncSession,
    recurring_client_slot_id: int,
    slot_date: date,
) -> None:
    """
    When a recurring-auto booking is cancelled, we skip auto-creating the same rule for that ISO week
    so the slot does not immediately refill.
    """
    ws = week_monday_containing(slot_date)
    await session.execute(
        text("""
            INSERT INTO recurring_materialization_week_skips (recurring_client_slot_id, week_start_monday)
            VALUES (:rid, :ws)
            ON CONFLICT (recurring_client_slot_id, week_start_monday) DO NOTHING
        """),
        {"rid": recurring_client_slot_id, "ws": ws},
    )


async def _recurring_client_is_sandbox(session: AsyncSession, client_id: int) -> bool:
    r = await session.execute(
        text("SELECT COALESCE(is_sandbox, false) FROM clients WHERE id = :id"),
        {"id": client_id},
    )
    row = r.fetchone()
    return bool(row and row[0])


async def _recurring_week_is_skipped(
    session: AsyncSession,
    recurring_client_slot_id: int,
    week_start_monday: date,
) -> bool:
    r = await session.execute(
        text("""
            SELECT 1 FROM recurring_materialization_week_skips
            WHERE recurring_client_slot_id = :rid AND week_start_monday = :ws
            LIMIT 1
        """),
        {"rid": recurring_client_slot_id, "ws": week_start_monday},
    )
    return r.fetchone() is not None


async def _has_booking_for_client_slot_pattern(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    slot_date: date,
    start_time: time,
) -> bool:
    st = start_time.replace(second=0, microsecond=0) if hasattr(start_time, "replace") else start_time
    r = await session.execute(
        text("""
            SELECT 1 FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.client_id = :cid
              AND s.slot_date = :d AND s.start_time = :st
              AND b.status NOT IN ('cancelled', 'declined')
            LIMIT 1
        """),
        {"tid": trainer_id, "cid": client_id, "d": slot_date, "st": st},
    )
    return r.fetchone() is not None


async def materialize_recurring_rule_for_week(
    session: AsyncSession,
    trainer_id: int,
    rec: dict,
    week_start: date,
    service_id: int,
) -> bool:
    """
    One recurring rule × one calendar week (week_start = Monday). Returns True if a new booking was created.
    Skips sandbox clients, past slots, week skips, duplicate same-time bookings, unavailable slots.
    """
    if await _recurring_client_is_sandbox(session, int(rec["client_id"])):
        return False
    rid = int(rec["id"])
    cid = int(rec["client_id"])
    dow = int(rec["day_of_week"])
    st_raw = rec["start_time"]
    st = st_raw.replace(second=0, microsecond=0) if hasattr(st_raw, "replace") else st_raw
    slot_date = week_start + timedelta(days=dow)
    if is_slot_start_in_past_local(slot_date, st):
        return False
    if await _recurring_week_is_skipped(session, rid, week_start):
        return False
    if await _has_booking_for_client_slot_pattern(session, trainer_id, cid, slot_date, st):
        return False
    slot_id = await find_available_slot_in_week(session, trainer_id, week_start, dow, st)
    if not slot_id:
        return False
    bid, _ = await create_booking(
        session,
        slot_id,
        trainer_id,
        cid,
        service_id=service_id,
        client_comment=None,
        client_request_id=None,
        created_by_trainer=True,
        recurring_client_slot_id=rid,
    )
    return bid is not None


async def materialize_recurring_horizon(
    session: AsyncSession,
    trainer_id: int,
    *,
    horizon_weeks: int,
    recurring_ids: list[int] | None = None,
) -> int:
    """
    Ensures auto-bookings exist for [this_week .. +horizon_weeks) for active recurring rules.
    Only trainers with CRM access (subscription) get auto materialization here.
    Returns count of newly created bookings.
    """
    from src.application.subscription_tier_use_cases import trainer_has_crm_access

    if not await trainer_has_crm_access(session, trainer_id):
        return 0
    service_id = await get_first_service_id_for_trainer(session, trainer_id)
    if not service_id:
        return 0
    recs = await list_active_recurring_for_trainer_week(session, trainer_id, this_week_monday())
    if recurring_ids is not None:
        wanted = set(int(x) for x in recurring_ids)
        recs = [r for r in recs if int(r["id"]) in wanted]
    h = max(1, min(52, int(horizon_weeks)))
    mono = this_week_monday()
    created = 0
    for i in range(h):
        ws = mono + timedelta(days=7 * i)
        for rec in recs:
            if await materialize_recurring_rule_for_week(session, trainer_id, rec, ws, service_id):
                created += 1
    return created


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
        if await materialize_recurring_rule_for_week(session, trainer_id, rec, week_start, service_id):
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
        if is_slot_start_in_past_local(slot_row[1], slot_row[2]):
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
