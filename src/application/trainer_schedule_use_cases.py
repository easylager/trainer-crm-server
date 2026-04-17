"""
Trainer schedule: weekly template (day + time) and generation of concrete slots.
All DB access via raw SQL.
"""
from datetime import date, time, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_schedule_preset import (
    allowed_start_minutes_from_preset,
    fixed_slot_duration_minutes,
    get_schedule_grid_preset_for_trainer,
    validate_duration_for_preset,
    validate_start_minutes_for_preset,
)


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
    minute_to_capacity: dict[int, int],
    duration_minutes: int,
    minute_to_service_id: dict[int, int | None] | None = None,
    group_arena_id: int | None = None,
) -> None:
    """
    Set template for one day: replace all template rows for that weekday.
    ``minute_to_capacity`` maps minutes-from-midnight (0–1439) to slot capacity (1 = individual, >1 = group).
    For capacity > 1, ``minute_to_service_id[m]`` must be the services.id for that group slot.
    ``group_arena_id`` is stored on each group row (capacity>1); if None, uses trainer default arena.
    Single transaction.
    """
    svc_map = minute_to_service_id or {}
    preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    validate_start_minutes_for_preset(set(minute_to_capacity.keys()), preset)
    validate_duration_for_preset(duration_minutes, preset)
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
    await session.execute(
        text("""
            DELETE FROM trainer_schedule_templates
            WHERE trainer_id = :tid AND day_of_week = :dow
        """),
        {"tid": trainer_id, "dow": day_of_week},
    )
    for m in sorted(minute_to_capacity.keys()):
        cap = max(1, min(int(minute_to_capacity[m]), 500))
        sid = svc_map.get(m)
        start_t = time_from_minutes(int(m))
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
                    "st": start_t,
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
                    "st": start_t,
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


def minutes_from_time(t: time) -> int:
    """Minutes from midnight (0–1439) for schedule keys."""
    return t.hour * 60 + t.minute


def time_from_minutes(m: int) -> time:
    """Build time from minutes from midnight; raises ValueError if out of range."""
    if m < 0 or m > 23 * 60 + 59:
        raise ValueError("start time out of range")
    return time(m // 60, m % 60)


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
    preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    fixed_dur = fixed_slot_duration_minutes(preset)
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
            row_dur = int(t["duration_minutes"])
            slot_dur = fixed_dur if fixed_dur is not None else row_dur
            end_time = _time_end(start_time, slot_dur)
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
    preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    fixed_dur = fixed_slot_duration_minutes(preset)
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
            row_dur = int(t["duration_minutes"])
            slot_dur = fixed_dur if fixed_dur is not None else row_dur
            end_time = _time_end(start_time, slot_dur)
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
    start_minutes: set[int],
    duration_minutes: int,
) -> int:
    """
    Create slots for one day in a specific week. week_start = Monday; day_of_week 0–6.
    ``start_minutes`` are minutes from midnight (0–1439) for each slot start.
    Returns number of slots created.
    """
    slot_date = week_start + timedelta(days=day_of_week)
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
    preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    validate_start_minutes_for_preset({int(m) for m in start_minutes}, preset)
    validate_duration_for_preset(duration_minutes, preset)
    created = 0
    for m in sorted(start_minutes):
        start_time = time_from_minutes(int(m))
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
    start_minutes: set[int],
    duration_minutes: int = DEFAULT_SLOT_DURATION_MINUTES,
    capacity: int = 1,
    group_service_id: int | None = None,
    slot_arena_id: int | None = None,
) -> None:
    """
    Set slots for one calendar day.

    - Removes only **available individual** slots whose start time is **not** in ``start_minutes``
      (minutes from midnight). Booked slots are never removed.
    - Inserts a slot for each minute key in ``start_minutes`` that does not yet exist, using ``capacity``.
    - **Does not** change ``capacity`` on slots that already exist — avoids turning every slot
      into a group slot when the trainer edits the day and only wants new times to use the form value.
    - Slots materialized from training groups (``training_group_id IS NOT NULL``) are intentionally
      outside this flow and are not touched or used for overlap checks here.
    For ``capacity`` > 1, ``group_service_id`` must be set (group slot is tied to that service).
    """
    cap = max(1, min(int(capacity), 500))
    if cap > 1 and group_service_id is None:
        raise ValueError("Group slot requires group_service_id")
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
    arena_for_new_slots = slot_arena_id if slot_arena_id is not None else default_arena
    minute_set = {int(m) for m in start_minutes if 0 <= int(m) <= 23 * 60 + 59}
    preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    validate_start_minutes_for_preset(minute_set, preset)
    validate_duration_for_preset(duration_minutes, preset)
    minute_list = sorted(minute_set)

    booking_guard = """
              AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.slot_id = slots.id AND b.status IN ('pending', 'confirmed')
              )
    """

    if not minute_list:
        await session.execute(
            text(
                """
            DELETE FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status = 'available'
              AND training_group_id IS NULL
            """
                + booking_guard
            ),
            {"tid": trainer_id, "d": slot_date},
        )
        await session.commit()
        return

    in_clause = ", ".join(str(int(m)) for m in minute_list)
    await session.execute(
        text(
            f"""
            DELETE FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status = 'available'
              AND training_group_id IS NULL
            """
            + booking_guard
            + f"""
              AND (
                EXTRACT(HOUR FROM start_time)::int * 60 + EXTRACT(MINUTE FROM start_time)::int
              ) NOT IN ({in_clause})
        """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    r = await session.execute(
        text("""
            SELECT EXTRACT(HOUR FROM start_time)::int * 60 + EXTRACT(MINUTE FROM start_time)::int
            FROM slots
            WHERE trainer_id = :tid AND slot_date = :d
              AND training_group_id IS NULL
        """),
        {"tid": trainer_id, "d": slot_date},
    )
    existing_minutes = {int(row[0]) for row in r.fetchall()}
    r_iv = await session.execute(
        text(
            """
            SELECT
              (EXTRACT(HOUR FROM start_time)::int * 60 + EXTRACT(MINUTE FROM start_time)::int) AS sm,
              (EXTRACT(HOUR FROM end_time)::int * 60 + EXTRACT(MINUTE FROM end_time)::int) AS em
            FROM slots
            WHERE trainer_id = :tid AND slot_date = :d
              AND status != 'cancelled'
              AND training_group_id IS NULL
            ORDER BY start_time, id
            """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    existing_intervals: list[tuple[int, int]] = []
    for row in r_iv.fetchall():
        sm = int(row[0])
        em = int(row[1])
        if em < sm:
            em = sm + 24 * 60
        existing_intervals.append((sm, em))
    # Track intervals inserted in this transaction to guard against overlaps inside payload itself.
    new_intervals: list[tuple[int, int]] = []
    for m in minute_list:
        if int(m) in existing_minutes:
            continue
        start_m = int(m)
        end_m = start_m + int(duration_minutes)
        for sm, em in existing_intervals:
            if _intervals_overlap_half_open(start_m, end_m, sm, em):
                raise ValueError("Время пересекается с другим слотом в расписании.")
        for sm, em in new_intervals:
            if _intervals_overlap_half_open(start_m, end_m, sm, em):
                raise ValueError("Время пересекается с другим слотом в расписании.")
        start_time = time_from_minutes(int(m))
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
        new_intervals.append((start_m, end_m))
    await session.commit()


def _intervals_overlap_half_open(a0: int, a1: int, b0: int, b1: int) -> bool:
    """Half-open [a0,a1) vs [b0,b1)."""
    return a0 < b1 and b0 < a1


async def ensure_individual_slot_for_quick_book(
    session: AsyncSession,
    trainer_id: int,
    slot_date: date,
    start_minutes: int,
    duration_minutes: int = DEFAULT_SLOT_DURATION_MINUTES,
) -> int:
    """
    Returns slot_id for an individual slot at start_minutes (arena schedule grid, same rules as schedule editor).
    Reuses an existing empty slot if it matches the same [start, end) interval.

    Raises ValueError on invalid time, group slot, booked slot, or interval overlap.
    """
    dm = int(duration_minutes)
    if dm < 15 or dm > 24 * 60:
        raise ValueError("Некорректная длительность")
    if start_minutes < 0 or start_minutes > 23 * 60 + 59:
        raise ValueError("Некорректное время начала")
    preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    if start_minutes not in allowed_start_minutes_from_preset(preset):
        raise ValueError("Время начала не соответствует сетке площадки.")
    validate_duration_for_preset(dm, preset)
    new_end = start_minutes + dm
    if new_end > 24 * 60:
        raise ValueError("Некорректная длительность для выбранного времени")

    start_t = time_from_minutes(start_minutes)
    end_t = _time_end(start_t, dm)

    r = await session.execute(
        text(
            """
            SELECT s.id,
              (EXTRACT(HOUR FROM s.start_time)::int * 60 + EXTRACT(MINUTE FROM s.start_time)::int) AS sm,
              (EXTRACT(HOUR FROM s.end_time)::int * 60 + EXTRACT(MINUTE FROM s.end_time)::int) AS em,
              s.capacity,
              (SELECT COUNT(*)::int FROM bookings b
               WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')) AS active_cnt
            FROM slots s
            WHERE s.trainer_id = :tid AND s.slot_date = :d AND s.status != 'cancelled'
            ORDER BY s.start_time, s.id
            """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    for row in r.fetchall():
        sid = int(row[0])
        sm = int(row[1])
        em = int(row[2])
        cap = max(1, int(row[3] or 1))
        active_cnt = int(row[4] or 0)
        if em < sm:
            em = sm + 24 * 60
        if not _intervals_overlap_half_open(start_minutes, new_end, sm, em):
            continue
        if cap > 1:
            raise ValueError(
                "На это время уже есть групповой слот — используйте расписание.",
            )
        if sm == start_minutes and em == new_end:
            if active_cnt >= 1:
                raise ValueError("Это время уже занято.")
            return sid
        if active_cnt >= 1:
            raise ValueError("Это время уже занято.")
        raise ValueError("Время пересекается с другим слотом в расписании.")

    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
    r2 = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id, arena_id)
            VALUES (:tid, :d, :st, :end, 'available', 1, NULL, :aid)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": slot_date,
            "st": start_t,
            "end": end_t,
            "aid": default_arena,
        },
    )
    new_id = r2.fetchone()
    if not new_id:
        raise ValueError("Не удалось создать слот")
    return int(new_id[0])


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
