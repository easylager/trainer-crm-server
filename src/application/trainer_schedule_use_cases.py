"""
Trainer schedule: weekly template (day + time) and generation of concrete slots.
All DB access via raw SQL.
"""
from datetime import date, time, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def this_week_monday() -> date:
    """Monday of the current week (ISO: Mon=0)."""
    today = date.today()
    return today - timedelta(days=today.weekday())


def next_week_monday() -> date:
    """Monday of the next week."""
    return this_week_monday() + timedelta(days=7)


async def list_templates(session: AsyncSession, trainer_id: int) -> list[dict]:
    """List schedule templates for the trainer. Sorted by day_of_week, start_time."""
    r = await session.execute(
        text("""
            SELECT id, trainer_id, day_of_week, start_time, duration_minutes
            FROM trainer_schedule_templates
            WHERE trainer_id = :tid
            ORDER BY day_of_week, start_time
        """),
        {"tid": trainer_id},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "trainer_id": row[1],
            "day_of_week": row[2],
            "start_time": row[3] if hasattr(row[3], "isoformat") else str(row[3]),
            "duration_minutes": row[4],
        }
        for row in rows
    ]


async def add_template(
    session: AsyncSession,
    trainer_id: int,
    day_of_week: int,
    start_time: time,
    duration_minutes: int = 60,
) -> int:
    """Add one weekly template. Returns template id."""
    r = await session.execute(
        text("""
            INSERT INTO trainer_schedule_templates (trainer_id, day_of_week, start_time, duration_minutes)
            VALUES (:tid, :dow, :st, :dur)
            RETURNING id
        """),
        {"tid": trainer_id, "dow": day_of_week, "st": start_time, "dur": duration_minutes},
    )
    (pk,) = r.fetchone()
    await session.commit()
    return pk


async def delete_template(session: AsyncSession, trainer_id: int, template_id: int) -> bool:
    """Remove a template. Returns True if deleted."""
    r = await session.execute(
        text("""
            DELETE FROM trainer_schedule_templates
            WHERE id = :id AND trainer_id = :tid
            RETURNING id
        """),
        {"id": template_id, "tid": trainer_id},
    )
    deleted = r.fetchone() is not None
    if deleted:
        await session.commit()
    return deleted


async def replace_templates_for_day(
    session: AsyncSession,
    trainer_id: int,
    day_of_week: int,
    start_hours: set[int],
    duration_minutes: int,
) -> None:
    """
    Set template for one day: remove all existing slots for that day, then add one per hour.
    Single transaction.
    """
    await session.execute(
        text("""
            DELETE FROM trainer_schedule_templates
            WHERE trainer_id = :tid AND day_of_week = :dow
        """),
        {"tid": trainer_id, "dow": day_of_week},
    )
    for h in sorted(start_hours):
        await session.execute(
            text("""
                INSERT INTO trainer_schedule_templates (trainer_id, day_of_week, start_time, duration_minutes)
                VALUES (:tid, :dow, :st, :dur)
            """),
            {
                "tid": trainer_id,
                "dow": day_of_week,
                "st": time(h, 0),
                "dur": duration_minutes,
            },
        )
    await session.commit()


def _time_end(start: time, duration_minutes: int) -> time:
    """start + duration_minutes as time (no date)."""
    from datetime import datetime, timedelta
    d = datetime.combine(date.today(), start) + timedelta(minutes=duration_minutes)
    return d.time()


async def generate_slots_for_week(
    session: AsyncSession, trainer_id: int, week_start: date
) -> int:
    """
    From templates, create slots for one calendar week (Mon–Sun).
    week_start = Monday of that week. Skips if slot already exists.
    Returns number of new slots created.
    """
    templates = await list_templates(session, trainer_id)
    if not templates:
        return 0
    created = 0
    for day_offset in range(7):
        d = week_start + timedelta(days=day_offset)
        dow = day_offset  # 0=Monday
        for t in templates:
            if t["day_of_week"] != dow:
                continue
            st = t["start_time"]
            if hasattr(st, "isoformat"):
                start_time = st
            else:
                parts = str(st).split(":")
                start_time = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            end_time = _time_end(start_time, t["duration_minutes"])
            r = await session.execute(
                text("""
                    SELECT 1 FROM slots
                    WHERE trainer_id = :tid AND slot_date = :d AND start_time = :st AND status != 'cancelled'
                """),
                {"tid": trainer_id, "d": d, "st": start_time},
            )
            if r.fetchone():
                continue
            await session.execute(
                text("""
                    INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                    VALUES (:tid, :d, :st, :end, 'available')
                """),
                {"tid": trainer_id, "d": d, "st": start_time, "end": end_time},
            )
            created += 1
    if created:
        await session.commit()
    return created


async def replace_week_with_template(
    session: AsyncSession,
    trainer_id: int,
    week_start: date,
) -> int:
    """
    Overwrite week with template: delete all available slots in the week range,
    then create slots from template. Booked slots are left unchanged.
    Returns number of slots created.
    """
    week_end = week_start + timedelta(days=6)
    await session.execute(
        text("""
            DELETE FROM slots
            WHERE trainer_id = :tid AND slot_date >= :from_d AND slot_date <= :to_d AND status = 'available'
        """),
        {"tid": trainer_id, "from_d": week_start, "to_d": week_end},
    )
    created = 0
    templates = await list_templates(session, trainer_id)
    if not templates:
        await session.commit()
        return 0
    for day_offset in range(7):
        d = week_start + timedelta(days=day_offset)
        dow = day_offset
        for t in templates:
            if t["day_of_week"] != dow:
                continue
            st = t["start_time"]
            if hasattr(st, "isoformat"):
                start_time = st
            else:
                parts = str(st).split(":")
                start_time = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            end_time = _time_end(start_time, t["duration_minutes"])
            await session.execute(
                text("""
                    INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                    VALUES (:tid, :d, :st, :end, 'available')
                """),
                {"tid": trainer_id, "d": d, "st": start_time, "end": end_time},
            )
            created += 1
    await session.commit()
    return created


async def add_slots_for_week(
    session: AsyncSession,
    trainer_id: int,
    week_start: date,
    day_of_week: int,
    hours: set[int],
    duration_minutes: int,
) -> int:
    """
    Create slots for one day in a specific week. week_start = Monday; day_of_week 0–6.
    Returns number of slots created.
    """
    slot_date = week_start + timedelta(days=day_of_week)
    created = 0
    for h in sorted(hours):
        start_time = time(h, 0)
        end_time = _time_end(start_time, duration_minutes)
        r = await session.execute(
            text("""
                SELECT 1 FROM slots
                WHERE trainer_id = :tid AND slot_date = :d AND start_time = :st AND status != 'cancelled'
            """),
            {"tid": trainer_id, "d": slot_date, "st": start_time},
        )
        if r.fetchone():
            continue
        await session.execute(
            text("""
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                VALUES (:tid, :d, :st, :end, 'available')
            """),
            {"tid": trainer_id, "d": slot_date, "st": start_time, "end": end_time},
        )
        created += 1
    if created:
        await session.commit()
    return created


DEFAULT_SLOT_DURATION_MINUTES = 60


async def replace_slots_for_day(
    session: AsyncSession,
    trainer_id: int,
    slot_date: date,
    start_hours: set[int],
    duration_minutes: int = DEFAULT_SLOT_DURATION_MINUTES,
) -> None:
    """
    Set slots for one calendar day: remove all available slots for that date,
    then create one slot per hour. Booked slots are left unchanged.
    """
    await session.execute(
        text("""
            DELETE FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status = 'available'
        """),
        {"tid": trainer_id, "d": slot_date},
    )
    for h in sorted(start_hours):
        start_time = time(h, 0)
        end_time = _time_end(start_time, duration_minutes)
        await session.execute(
            text("""
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                VALUES (:tid, :d, :st, :end, 'available')
            """),
            {"tid": trainer_id, "d": slot_date, "st": start_time, "end": end_time},
        )
    await session.commit()


async def list_slots(
    session: AsyncSession,
    trainer_id: int,
    from_date: date,
    to_date: date,
) -> list[dict]:
    """List slots in date range (inclusive). Ordered by slot_date, start_time."""
    r = await session.execute(
        text("""
            SELECT id, slot_date, start_time, end_time, status
            FROM slots
            WHERE trainer_id = :tid AND slot_date >= :from_d AND slot_date <= :to_d
            ORDER BY slot_date, start_time
        """),
        {"tid": trainer_id, "from_d": from_date, "to_d": to_date},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "slot_date": row[1],
            "start_time": row[2],
            "end_time": row[3],
            "status": row[4],
        }
        for row in rows
    ]


async def delete_slot(
    session: AsyncSession,
    trainer_id: int,
    slot_id: int,
) -> bool:
    """
    Delete one applied slot. Only available slots can be removed; booked ones are left unchanged.
    Returns True if deleted, False if slot not found or not available.
    """
    r = await session.execute(
        text("""
            DELETE FROM slots
            WHERE id = :id AND trainer_id = :tid AND status = 'available'
            RETURNING id
        """),
        {"id": slot_id, "tid": trainer_id},
    )
    deleted = r.fetchone() is not None
    if deleted:
        await session.commit()
    return deleted


async def get_slot(
    session: AsyncSession,
    slot_id: int,
) -> dict | None:
    """Get one slot by id. Returns dict with slot_date, start_time, end_time, status or None."""
    r = await session.execute(
        text("""
            SELECT id, slot_date, start_time, end_time, status
            FROM slots WHERE id = :id
        """),
        {"id": slot_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "slot_date": row[1],
        "start_time": row[2],
        "end_time": row[3],
        "status": row[4],
    }


async def book_slot(
    session: AsyncSession,
    slot_id: int,
    trainer_id: int,
) -> bool:
    """
    Book a slot (client chose it). Sets status to 'booked' if slot is available and belongs to trainer.
    Returns True if booked, False otherwise.
    """
    r = await session.execute(
        text("""
            UPDATE slots
            SET status = 'booked'
            WHERE id = :id AND trainer_id = :tid AND status = 'available'
            RETURNING id
        """),
        {"id": slot_id, "tid": trainer_id},
    )
    ok = r.fetchone() is not None
    if ok:
        await session.commit()
    return ok
