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
    get_arena_schedule_preset_raw,
    get_schedule_grid_preset_for_trainer,
    get_schedule_grid_preset_for_trainer_arena,
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


def _hhmm(minutes: int) -> str:
    """Minutes-from-midnight as HH:MM — for error messages a trainer has to act on."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


async def _presets_by_arena(
    session: AsyncSession,
    arena_ids: set[int | None],
    trainer_preset: dict,
) -> dict[int | None, dict]:
    """
    Grid preset per venue for one day's rows.

    ``None`` means the row stores ``arena_id`` NULL — «wherever the trainer works by default» —
    so it is judged by the trainer's own grid, exactly as materialization will resolve it.
    """
    out: dict[int | None, dict] = {None: trainer_preset}
    for aid in arena_ids:
        if aid is None or aid in out:
            continue
        out[aid] = await get_arena_schedule_preset_raw(session, int(aid))
    return out


async def _arena_names(session: AsyncSession, arena_ids: set[int]) -> dict[int, str]:
    if not arena_ids:
        return {}
    r = await session.execute(
        text("SELECT id, name FROM arenas WHERE id = ANY(:ids)"),
        {"ids": sorted(arena_ids)},
    )
    return {int(row[0]): row[1] for row in r.fetchall()}


async def replace_templates_for_day(
    session: AsyncSession,
    trainer_id: int,
    day_of_week: int,
    minute_to_capacity: dict[int, int],
    duration_minutes: int,
    minute_to_service_id: dict[int, int | None] | None = None,
    group_arena_id: int | None = None,
    minute_to_duration: dict[int, int] | None = None,
    minute_to_arena_id: dict[int, int] | None = None,
    only_capacity_one: bool = False,
) -> None:
    """
    Set template for one day: replace all template rows for that weekday.
    ``minute_to_capacity`` maps minutes-from-midnight (0–1439) to slot capacity (1 = individual, >1 = group).
    For capacity > 1, ``minute_to_service_id[m]`` must be the services.id for that group slot.
    ``group_arena_id`` is stored on each group row (capacity>1); if None, uses trainer default arena.
    ``minute_to_arena_id``: optional venue per individual start minute (capacity 1); stored on template row,
    reproduced on generated slots; omitted key → ``arena_id`` NULL → materialization uses trainer default arena.
    ``minute_to_duration``: optional per-start duration (minutes). When any start is off the arena grid or
    durations differ, preset start-grid validation is skipped (same idea as calendar ``slot_entries``).
    Each row's duration is checked against the preset of **its own** arena — a trainer working two
    venues with different fixed durations must be able to save both in one day.

    ``only_capacity_one``: replace **individual** rows only and leave group rows (capacity > 1)
    of that weekday alone. For callers that cannot express group classes at all — onboarding —
    a full replace silently deletes a surface they never showed the trainer. Surviving rows still
    take part in the overlap check, so an individual slot can never be laid over a group class.
    Single transaction.
    """
    svc_map = minute_to_service_id or {}
    preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    allowed = allowed_start_minutes_from_preset(preset)
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
    dur_map: dict[int, int] = {}
    for m in minute_to_capacity.keys():
        mi = int(m)
        if minute_to_duration is not None and mi in minute_to_duration:
            dur_map[mi] = max(15, min(480, int(minute_to_duration[mi])))
        else:
            dur_map[mi] = max(15, min(480, int(duration_minutes)))

    # Which venue does each row belong to? Individual rows carry their own (NULL = the trainer's
    # default, resolved at materialization); group rows all sit on ``group_arena_id``.
    row_arena: dict[int, int | None] = {}
    for m in minute_to_capacity.keys():
        mi = int(m)
        if int(minute_to_capacity[m]) > 1:
            row_arena[mi] = int(group_arena_id) if group_arena_id is not None else default_arena
        else:
            row_arena[mi] = (minute_to_arena_id or {}).get(mi)
    presets_by_arena = await _presets_by_arena(session, set(row_arena.values()), preset)
    arena_names = await _arena_names(session, {a for a in row_arena.values() if a is not None})

    # Duration is checked against the preset of the row's OWN arena. Reading a single preset for
    # the whole call (the trainer's primary) made a second venue with a different fixed duration
    # unsavable, and said so in a message naming neither venue nor value.
    for mi in sorted(dur_map.keys()):
        fixed = fixed_slot_duration_minutes(presets_by_arena[row_arena[mi]])
        if fixed is None or dur_map[mi] == fixed:
            continue
        aid = row_arena[mi]
        where = f"«{arena_names[aid]}»" if aid in arena_names else "этой площадки"
        raise ValueError(
            f"{_hhmm(mi)}: длительность на {where} зафиксирована — {fixed} мин, "
            f"а в слоте {dur_map[mi]} мин."
        )

    # Start alignment stays a whole-day check against the trainer's grid: «Точное время» places
    # starts off it on purpose, and one off-grid start relaxes the day. An empty day has nothing
    # to align — it is a clear, not a schedule.
    off_grid = any(int(m) not in allowed for m in minute_to_capacity.keys())
    unique_durs = {dur_map[int(m)] for m in minute_to_capacity.keys()}
    loose_alignment = off_grid or len(unique_durs) > 1
    if minute_to_capacity and not loose_alignment:
        validate_start_minutes_for_preset(set(minute_to_capacity.keys()), preset)

    # Each interval carries its own arena so a collision can be named, not just reported —
    # with two venues in one day, «слоты пересекаются» stopped being enough to act on.
    intervals: list[tuple[int, int, int | None]] = sorted(
        (int(m), int(m) + dur_map[int(m)], row_arena[int(m)]) for m in minute_to_capacity.keys()
    )
    if only_capacity_one:
        # Rows this call will not delete are still part of the day and must not be overlapped.
        r_keep = await session.execute(
            text("""
                SELECT start_time, duration_minutes, arena_id
                FROM trainer_schedule_templates
                WHERE trainer_id = :tid AND day_of_week = :dow AND capacity > 1
            """),
            {"tid": trainer_id, "dow": day_of_week},
        )
        for row in r_keep.fetchall():
            m0 = minutes_from_time(row[0])
            keep_arena = int(row[2]) if row[2] is not None else None
            intervals.append((m0, m0 + int(row[1]), keep_arena))
            if keep_arena is not None and keep_arena not in arena_names:
                arena_names.update(await _arena_names(session, {keep_arena}))
        intervals.sort()
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            a0, a1, a_aid = intervals[i]
            b0, b1, b_aid = intervals[j]
            if _intervals_overlap_half_open(a0, a1, b0, b1):
                a_where = f"«{arena_names[a_aid]}»" if a_aid in arena_names else "по умолчанию"
                b_where = f"«{arena_names[b_aid]}»" if b_aid in arena_names else "по умолчанию"
                raise ValueError(
                    f"{_hhmm(a0)}–{_hhmm(a1)} ({a_where}) пересекается с "
                    f"{_hhmm(b0)}–{_hhmm(b1)} ({b_where})."
                )

    await session.execute(
        text(
            """
            DELETE FROM trainer_schedule_templates
            WHERE trainer_id = :tid AND day_of_week = :dow
            """
            + (" AND capacity = 1" if only_capacity_one else "")
        ),
        {"tid": trainer_id, "dow": day_of_week},
    )
    for m in sorted(minute_to_capacity.keys()):
        cap = max(1, min(int(minute_to_capacity[m]), 500))
        sid = svc_map.get(m)
        start_t = time_from_minutes(int(m))
        row_dur = dur_map[int(m)]
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
                    "dur": row_dur,
                    "cap": cap,
                    "svc": int(sid),
                    "aid": aid,
                },
            )
        else:
            indiv_aid = None
            if minute_to_arena_id is not None:
                indiv_aid = minute_to_arena_id.get(int(m))
            await session.execute(
                text("""
                    INSERT INTO trainer_schedule_templates
                        (trainer_id, day_of_week, start_time, duration_minutes, capacity, service_id, arena_id)
                    VALUES (:tid, :dow, :st, :dur, :cap, NULL, :aid)
                """),
                {
                    "tid": trainer_id,
                    "dow": day_of_week,
                    "st": start_t,
                    "dur": row_dur,
                    "cap": cap,
                    "aid": indiv_aid,
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


async def trainer_has_slot_overlapping_interval(
    session: AsyncSession,
    trainer_id: int,
    slot_date: date,
    start_t: time,
    end_t: time,
) -> bool:
    """True if any non-cancelled slot on that calendar day intersects [start_t, end_t)."""
    r = await session.execute(
        text(
            """
            SELECT 1 FROM slots
            WHERE trainer_id = :tid
              AND slot_date = :d
              AND status != 'cancelled'
              AND start_time < :end_t
              AND end_time > :start_t
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "d": slot_date, "start_t": start_t, "end_t": end_t},
    )
    return r.fetchone() is not None


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
            if await trainer_has_slot_overlapping_interval(session, trainer_id, d, start_time, end_time):
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
    then create slots from template. Booked (and other non-deleted) slots stay;
    new rows are skipped when the interval would overlap an existing non-cancelled slot.
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
            # Booked / past sessions keep rows with status != 'available'; do not stack a template slot on top.
            if await trainer_has_slot_overlapping_interval(session, trainer_id, d, start_time, end_time):
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
        if await trainer_has_slot_overlapping_interval(session, trainer_id, slot_date, start_time, end_time):
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


DEFAULT_SLOT_DURATION_MINUTES = 45


async def replace_slots_for_day(
    session: AsyncSession,
    trainer_id: int,
    slot_date: date,
    start_minutes: set[int],
    duration_minutes: int = DEFAULT_SLOT_DURATION_MINUTES,
    capacity: int = 1,
    group_service_id: int | None = None,
    slot_arena_id: int | None = None,
    per_slot_duration: dict[int, int] | None = None,
    per_slot_arena_id: dict[int, int] | None = None,
) -> None:
    """
    Set slots for one calendar day.

    - Removes only **available individual** slots whose start time is **not** in ``start_minutes``
      (minutes from midnight). Booked slots are never removed.
    - Inserts a slot for each minute key in ``start_minutes`` that does not yet exist, using ``capacity``.
    - **Does not** change ``capacity`` on slots that already exist.
    - Slots materialized from training groups are not touched.
    - ``per_slot_duration``: optional start_minute→duration_minutes map for precise (off-grid) slots.
      When provided, grid validation is skipped — caller is responsible for sensible times.
    For ``capacity`` > 1, ``group_service_id`` must be set.
    ``per_slot_arena_id``: optional start_minute → arena_id overrides for newly inserted slots
    (e.g. precise-time entries on a secondary venue while grid stays on default arena).
    """
    cap = max(1, min(int(capacity), 500))
    if cap > 1 and group_service_id is None:
        raise ValueError("Group slot requires group_service_id")
    default_arena = await trainer_default_slot_arena_id(session, trainer_id)
    arena_for_new_slots = slot_arena_id if slot_arena_id is not None else default_arena
    minute_set = {int(m) for m in start_minutes if 0 <= int(m) <= 23 * 60 + 59}
    preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    # Skip grid-alignment check for precise off-grid entries (per_slot_duration path).
    if per_slot_duration is None:
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
        # Per-slot duration for precise/off-grid entries; fall back to uniform duration.
        slot_dur = per_slot_duration[start_m] if per_slot_duration and start_m in per_slot_duration else int(duration_minutes)
        end_m = start_m + slot_dur
        for sm, em in existing_intervals:
            if _intervals_overlap_half_open(start_m, end_m, sm, em):
                raise ValueError("Время пересекается с другим слотом в расписании.")
        for sm, em in new_intervals:
            if _intervals_overlap_half_open(start_m, end_m, sm, em):
                raise ValueError("Время пересекается с другим слотом в расписании.")
        start_time = time_from_minutes(int(m))
        end_time = _time_end(start_time, slot_dur)
        svc = int(group_service_id) if cap > 1 else None
        insert_aid = arena_for_new_slots
        if per_slot_arena_id and start_m in per_slot_arena_id:
            insert_aid = per_slot_arena_id[start_m]
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
                "aid": insert_aid,
            },
        )
        new_intervals.append((start_m, end_m))
    await session.commit()


def _intervals_overlap_half_open(a0: int, a1: int, b0: int, b1: int) -> bool:
    """Half-open [a0,a1) vs [b0,b1)."""
    return a0 < b1 and b0 < a1


async def _delete_empty_individual_slot(
    session: AsyncSession,
    trainer_id: int,
    slot_id: int,
) -> None:
    """Drop an available individual slot with no pending/confirmed bookings."""
    r = await session.execute(
        text(
            """
            SELECT s.capacity,
              (SELECT COUNT(*)::int FROM bookings b
               WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')) AS active_cnt
            FROM slots s
            WHERE s.id = :sid AND s.trainer_id = :tid AND s.status != 'cancelled'
            """
        ),
        {"sid": slot_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return
    cap = max(1, int(row[0] or 1))
    active_cnt = int(row[1] or 0)
    if cap > 1 or active_cnt >= 1:
        raise ValueError("Это время уже занято.")
    await session.execute(
        text("DELETE FROM slots WHERE id = :sid AND trainer_id = :tid"),
        {"sid": slot_id, "tid": trainer_id},
    )


async def ensure_individual_slot_for_quick_book(
    session: AsyncSession,
    trainer_id: int,
    slot_date: date,
    start_minutes: int,
    duration_minutes: int = DEFAULT_SLOT_DURATION_MINUTES,
    *,
    allow_off_grid_interval: bool = False,
    arena_id: int | None = None,
) -> int:
    """
    Returns slot_id for an individual slot at start_minutes (arena schedule grid, same rules as schedule editor).
    Reuses an existing empty slot when the interval matches; updates ``arena_id`` when the trainer picks another venue.

    Empty overlapping slots on other venues (or partial overlaps) are removed automatically so the trainer can
    book without manually deleting free windows first. Booked or group slots still block the interval.

    ``allow_off_grid_interval``: skip arena/uniform grid checks — used when copying an interval from an existing
    booking («same time next week» / precise-time sessions).

    Raises ValueError on invalid time, group slot, or occupied interval.
    """
    dm = int(duration_minutes)
    if allow_off_grid_interval:
        # Mirror a real session interval (may start at :07 etc.); keep overlap checks below.
        if dm < 5 or dm > 24 * 60:
            raise ValueError("Некорректная длительность")
    elif dm < 15 or dm > 24 * 60:
        raise ValueError("Некорректная длительность")
    if start_minutes < 0 or start_minutes > 23 * 60 + 59:
        raise ValueError("Некорректное время начала")
    slot_arena_id: int | None
    if arena_id is not None:
        r_own = await session.execute(
            text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
            {"tid": trainer_id, "aid": int(arena_id)},
        )
        if not r_own.fetchone():
            raise ValueError("Площадка не привязана к вашему профилю")
        slot_arena_id = int(arena_id)
    else:
        slot_arena_id = await trainer_default_slot_arena_id(session, trainer_id)
    if not allow_off_grid_interval:
        if slot_arena_id is not None:
            preset = await get_schedule_grid_preset_for_trainer_arena(session, trainer_id, slot_arena_id)
        else:
            preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
        if start_minutes not in allowed_start_minutes_from_preset(preset):
            raise ValueError("Время начала не соответствует сетке площадки.")
        validate_duration_for_preset(dm, preset)
    new_end = start_minutes + dm
    if new_end > 24 * 60:
        raise ValueError("Некорректная длительность для выбранного времени")

    start_t = time_from_minutes(start_minutes)
    end_t = _time_end(start_t, dm)

    slot_arena_effective_default = await trainer_default_slot_arena_id(session, trainer_id)

    r = await session.execute(
        text(
            """
            SELECT s.id,
              (EXTRACT(HOUR FROM s.start_time)::int * 60 + EXTRACT(MINUTE FROM s.start_time)::int) AS sm,
              (EXTRACT(HOUR FROM s.end_time)::int * 60 + EXTRACT(MINUTE FROM s.end_time)::int) AS em,
              s.capacity,
              s.arena_id,
              (SELECT COUNT(*)::int FROM bookings b
               WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')) AS active_cnt
            FROM slots s
            WHERE s.trainer_id = :tid AND s.slot_date = :d AND s.status != 'cancelled'
            ORDER BY s.start_time, s.id
            """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    exact_reuse_id: int | None = None
    exact_arena_update_id: int | None = None
    partial_remove_ids: list[int] = []

    for row in r.fetchall():
        sid = int(row[0])
        sm = int(row[1])
        em = int(row[2])
        cap = max(1, int(row[3] or 1))
        row_arena_id: int | None = int(row[4]) if row[4] is not None else None
        row_effective_arena: int | None = (
            row_arena_id if row_arena_id is not None else slot_arena_effective_default
        )
        active_cnt = int(row[5] or 0)
        if em < sm:
            em = sm + 24 * 60
        if not _intervals_overlap_half_open(start_minutes, new_end, sm, em):
            continue
        if cap > 1:
            raise ValueError(
                "На это время уже есть групповой слот — используйте расписание.",
            )
        if active_cnt >= 1:
            raise ValueError("Это время уже занято.")
        if sm == start_minutes and em == new_end:
            if row_effective_arena == slot_arena_id:
                exact_reuse_id = sid
            else:
                exact_arena_update_id = sid
            continue
        partial_remove_ids.append(sid)

    keep_ids = {i for i in (exact_reuse_id, exact_arena_update_id) if i is not None}
    for sid in partial_remove_ids:
        if sid in keep_ids:
            continue
        await _delete_empty_individual_slot(session, trainer_id, sid)

    if exact_reuse_id is not None:
        return exact_reuse_id
    if exact_arena_update_id is not None:
        await session.execute(
            text(
                """
                UPDATE slots SET arena_id = :aid
                WHERE id = :sid AND trainer_id = :tid
                """
            ),
            {"aid": slot_arena_id, "sid": exact_arena_update_id, "tid": trainer_id},
        )
        return exact_arena_update_id

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
            "aid": slot_arena_id,
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
                   ar.address AS arena_address,
                   ar.latitude AS arena_latitude,
                   ar.longitude AS arena_longitude,
                   ac.name AS arena_city_name,
                   (SELECT COUNT(*)::int FROM bookings b
                    WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')) AS active_bookings
            FROM slots s
            LEFT JOIN training_groups tg ON tg.id = s.training_group_id
            LEFT JOIN services sv ON sv.id = s.service_id
            LEFT JOIN arenas ar ON ar.id = s.arena_id
            LEFT JOIN cities ac ON ac.id = ar.city_id
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
            "arena_address": (row[12] or "").strip() if row[12] else None,
            "arena_latitude": (float(row[13]) if row[13] is not None else None),
            "arena_longitude": (float(row[14]) if row[14] is not None else None),
            "arena_city_name": (row[15] or "").strip() if row[15] else None,
            "active_bookings": int(row[16] or 0),
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
