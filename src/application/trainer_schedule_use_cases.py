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


async def trainer_offers_service(session: AsyncSession, trainer_id: int, service_id: int) -> bool:
    r = await session.execute(
        text("SELECT 1 FROM trainer_services WHERE trainer_id = :tid AND service_id = :sid"),
        {"tid": trainer_id, "sid": service_id},
    )
    return r.fetchone() is not None


async def trainer_default_slot_arena_id(session: AsyncSession, trainer_id: int) -> int | None:
    """Primary arena, else MIN(trainer_arenas). Used when creating new slots."""
    r = await session.execute(
        text("SELECT primary_arena_id FROM trainers WHERE id = :tid"),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    r2 = await session.execute(
        text("SELECT MIN(arena_id) FROM trainer_arenas WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    v = r2.scalar()
    return int(v) if v is not None else None


async def list_templates(session: AsyncSession, trainer_id: int) -> list[dict]:
    """List schedule templates for the trainer. Sorted by day_of_week, start_time."""
    r = await session.execute(
        text("""
            SELECT id, trainer_id, day_of_week, start_time, duration_minutes, capacity, service_id, arena_id
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
            "capacity": int(row[5]) if row[5] is not None else 1,
            "service_id": int(row[6]) if len(row) > 6 and row[6] is not None else None,
            "arena_id": int(row[7]) if len(row) > 7 and row[7] is not None else None,
        }
        for row in rows
    ]


async def add_template(
    session: AsyncSession,
    trainer_id: int,
    day_of_week: int,
    start_time: time,
    duration_minutes: int = 60,
    capacity: int = 1,
) -> int:
    """Add one weekly template. Returns template id."""
    cap = max(1, min(int(capacity), 500))
    r = await session.execute(
        text("""
            INSERT INTO trainer_schedule_templates (trainer_id, day_of_week, start_time, duration_minutes, capacity)
            VALUES (:tid, :dow, :st, :dur, :cap)
            RETURNING id
        """),
        {"tid": trainer_id, "dow": day_of_week, "st": start_time, "dur": duration_minutes, "cap": cap},
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
    hour_to_capacity: dict[int, int],
    duration_minutes: int,
    hour_to_service_id: dict[int, int | None] | None = None,
    group_arena_id: int | None = None,
) -> None:
    """
    Set template for one day: replace all template rows for that weekday.
    ``hour_to_capacity`` maps hour (0–23) to slot capacity (1 = individual, >1 = group).
    For capacity > 1, ``hour_to_service_id[h]`` must be the services.id for that group slot.
    ``group_arena_id`` is stored on each group row (capacity>1); if None, uses trainer default arena.
    Single transaction.
    """
    svc_map = hour_to_service_id or {}
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
    await session.execute(
        text("""
            DELETE FROM trainer_schedule_templates
            WHERE trainer_id = :tid AND day_of_week = :dow
        """),
        {"tid": trainer_id, "dow": day_of_week},
    )
    for h in sorted(hour_to_capacity.keys()):
        cap = max(1, min(int(hour_to_capacity[h]), 500))
        sid = svc_map.get(h)
        if cap > 1:
            if sid is None:
                raise ValueError("Group template slot requires service_id")
            aid = int(group_arena_id) if group_arena_id is not None else default_arena
            await session.execute(
                text("""
                    INSERT INTO trainer_schedule_templates
                        (trainer_id, day_of_week, start_time, duration_minutes, capacity, service_id, arena_id)
                    VALUES (:tid, :dow, :st, :dur, :cap, :svc, :aid)
                """),
                {
                    "tid": trainer_id,
                    "dow": day_of_week,
                    "st": time(h, 0),
                    "dur": duration_minutes,
                    "cap": cap,
                    "svc": int(sid),
                    "aid": aid,
                },
            )
        else:
            await session.execute(
                text("""
                    INSERT INTO trainer_schedule_templates
                        (trainer_id, day_of_week, start_time, duration_minutes, capacity, service_id, arena_id)
                    VALUES (:tid, :dow, :st, :dur, :cap, NULL, NULL)
                """),
                {
                    "tid": trainer_id,
                    "dow": day_of_week,
                    "st": time(h, 0),
                    "dur": duration_minutes,
                    "cap": cap,
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
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
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
            cap = max(1, min(int(t.get("capacity") or 1), 500))
            tmpl_svc = t.get("service_id")
            svc = int(tmpl_svc) if tmpl_svc is not None else None
            if cap > 1 and svc is None:
                continue
            tmpl_arena = t.get("arena_id")
            slot_arena = int(tmpl_arena) if tmpl_arena is not None else default_arena
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
                    INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id, arena_id)
                    VALUES (:tid, :d, :st, :end, 'available', :cap, :svc, :aid)
                """),
                {
                    "tid": trainer_id,
                    "d": d,
                    "st": start_time,
                    "end": end_time,
                    "cap": cap,
                    "svc": svc,
                    "aid": slot_arena,
                },
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
              AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.slot_id = slots.id AND b.status IN ('pending', 'confirmed')
              )
        """),
        {"tid": trainer_id, "from_d": week_start, "to_d": week_end},
    )
    created = 0
    templates = await list_templates(session, trainer_id)
    if not templates:
        await session.commit()
        return 0
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
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
            cap = max(1, min(int(t.get("capacity") or 1), 500))
            tmpl_svc = t.get("service_id")
            svc = int(tmpl_svc) if tmpl_svc is not None else None
            if cap > 1 and svc is None:
                continue
            tmpl_arena = t.get("arena_id")
            slot_arena = int(tmpl_arena) if tmpl_arena is not None else default_arena
            await session.execute(
                text("""
                    INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id, arena_id)
                    VALUES (:tid, :d, :st, :end, 'available', :cap, :svc, :aid)
                """),
                {
                    "tid": trainer_id,
                    "d": d,
                    "st": start_time,
                    "end": end_time,
                    "cap": cap,
                    "svc": svc,
                    "aid": slot_arena,
                },
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
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
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
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id, arena_id)
                VALUES (:tid, :d, :st, :end, 'available', 1, NULL, :aid)
            """),
            {"tid": trainer_id, "d": slot_date, "st": start_time, "end": end_time, "aid": default_arena},
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
    capacity: int = 1,
    group_service_id: int | None = None,
    slot_arena_id: int | None = None,
) -> None:
    """
    Set slots for one calendar day.

    - Removes only slots for hours **not** in ``start_hours`` (empty available slots; never touches
      slots with active bookings).
    - Inserts a slot for each hour in ``start_hours`` that does not yet exist, using ``capacity``.
    - **Does not** change ``capacity`` on slots that already exist — avoids turning every hour
      into a group slot when the trainer edits the day and only wants new hours to use the form value.
    For ``capacity`` > 1, ``group_service_id`` must be set (group slot is tied to that service).
    """
    cap = max(1, min(int(capacity), 500))
    if cap > 1 and group_service_id is None:
        raise ValueError("Group slot requires group_service_id")
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
    arena_for_new_slots = slot_arena_id if slot_arena_id is not None else default_arena
    hour_list = sorted(h for h in start_hours if 0 <= h <= 23)

    booking_guard = """
              AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.slot_id = slots.id AND b.status IN ('pending', 'confirmed')
              )
    """

    if not hour_list:
        await session.execute(
            text(
                """
            DELETE FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status = 'available'
            """
                + booking_guard
            ),
            {"tid": trainer_id, "d": slot_date},
        )
        await session.commit()
        return

    in_clause = ", ".join(str(int(h)) for h in hour_list)
    await session.execute(
        text(
            f"""
            DELETE FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status = 'available'
            """
            + booking_guard
            + f"""
              AND EXTRACT(HOUR FROM start_time)::int NOT IN ({in_clause})
        """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    r = await session.execute(
        text("""
            SELECT EXTRACT(HOUR FROM start_time)::int FROM slots
            WHERE trainer_id = :tid AND slot_date = :d
        """),
        {"tid": trainer_id, "d": slot_date},
    )
    existing_hours = {int(row[0]) for row in r.fetchall()}
    for h in hour_list:
        if h in existing_hours:
            continue
        start_time = time(h, 0)
        end_time = _time_end(start_time, duration_minutes)
        svc = int(group_service_id) if cap > 1 else None
        await session.execute(
            text("""
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id, arena_id)
                VALUES (:tid, :d, :st, :end, 'available', :cap, :svc, :aid)
            """),
            {
                "tid": trainer_id,
                "d": slot_date,
                "st": start_time,
                "end": end_time,
                "cap": cap,
                "svc": svc,
                "aid": arena_for_new_slots,
            },
        )
    await session.commit()


async def list_slots(
    session: AsyncSession,
    trainer_id: int,
    from_date: date,
    to_date: date,
) -> list[dict]:
    """List slots in date range (inclusive). Ordered by slot_date, start_time.

    Slots tied to an archived training group are omitted (materialized rows may outlive the group).
    """
    r = await session.execute(
        text("""
            SELECT s.id, s.slot_date, s.start_time, s.end_time, s.status, s.capacity, s.service_id,
                   s.arena_id, s.training_group_id, tg.name,
                   sv.name AS service_name,
                   ar.name AS arena_name,
                   (SELECT COUNT(*)::int FROM bookings b
                    WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')) AS active_bookings
            FROM slots s
            LEFT JOIN training_groups tg ON tg.id = s.training_group_id
            LEFT JOIN services sv ON sv.id = s.service_id
            LEFT JOIN arenas ar ON ar.id = s.arena_id
            WHERE s.trainer_id = :tid AND s.slot_date >= :from_d AND s.slot_date <= :to_d
              AND (
                s.training_group_id IS NULL
                OR (tg.id IS NOT NULL AND tg.status != 'archived')
              )
            ORDER BY s.slot_date, s.start_time
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
            "capacity": max(1, int(row[5])),
            "service_id": int(row[6]) if row[6] is not None else None,
            "arena_id": int(row[7]) if row[7] is not None else None,
            "training_group_id": int(row[8]) if row[8] is not None else None,
            "training_group_name": (row[9] or "").strip() if row[8] is not None else None,
            "service_name": (row[10] or "").strip() if row[10] else None,
            "arena_name": (row[11] or "").strip() if row[11] else None,
            "active_bookings": int(row[12] or 0),
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
              AND training_group_id IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.slot_id = slots.id AND b.status IN ('pending', 'confirmed')
              )
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
    """Get one slot by id. Returns dict with trainer_id, slot_date, start_time, end_time, status or None."""
    r = await session.execute(
        text("""
            SELECT s.id, s.trainer_id, s.slot_date, s.start_time, s.end_time, s.status, s.capacity,
                   s.service_id, s.arena_id, s.training_group_id, tg.name
            FROM slots s
            LEFT JOIN training_groups tg ON tg.id = s.training_group_id
            WHERE s.id = :id
        """),
        {"id": slot_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "trainer_id": row[1],
        "slot_date": row[2],
        "start_time": row[3],
        "end_time": row[4],
        "status": row[5],
        "capacity": max(1, int(row[6])),
        "service_id": int(row[7]) if row[7] is not None else None,
        "arena_id": int(row[8]) if row[8] is not None else None,
        "training_group_id": int(row[9]) if row[9] is not None else None,
        "training_group_name": (row[10] or "").strip() if row[9] is not None else None,
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
