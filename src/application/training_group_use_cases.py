"""
Training groups (cohorts): roster, recurring schedule, slots materialization, catalog join requests.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.ttl_cache import invalidate_slots_for_trainer

# Group lifecycle
TG_DRAFT = "draft"
TG_RECRUITING = "recruiting"
TG_ACTIVE = "active"
TG_PAUSED = "paused"
TG_ARCHIVED = "archived"

MEMBER_ACTIVE = "active"
MEMBER_TRIAL = "trial"
MEMBER_WAITLIST = "waitlist"
MEMBER_LEFT = "left"

JOIN_PENDING = "pending"
JOIN_APPROVED = "approved"
JOIN_REJECTED = "rejected"

# How far ahead to create concrete slots (weeks)
SLOT_HORIZON_WEEKS = 8


class TrainingGroupScheduleConflictError(Exception):
    """New group schedule collides with a booking, recurring client, group slot, or group template row."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _schedule_conflict_same_venue(slot_arena_id: int | None, group_arena_id: int | None) -> bool:
    """
    True when the slot and the new group occupy the same scheduling lane.

    If one side has no venue (NULL), we treat it as overlapping the trainer's calendar for that time
    (takeover / conflict). If both are set and differ, the trainer may run two sessions at different venues.
    """
    if slot_arena_id is None or group_arena_id is None:
        return True
    return int(slot_arena_id) == int(group_arena_id)


def _parse_rule_start_time(rule: dict) -> time:
    parts = str(rule["start_time"]).split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def _materialize_date_range(
    season_start_date: date | None, *, weeks_ahead: int = SLOT_HORIZON_WEEKS
) -> tuple[date, date]:
    today = date.today()
    start_d = today
    if season_start_date and season_start_date > today:
        start_d = season_start_date
    end_d = start_d + timedelta(weeks=weeks_ahead)
    return start_d, end_d


def _time_end(start: time, duration_minutes: int) -> time:
    from datetime import date as ddate

    d = datetime.combine(ddate.today(), start) + timedelta(minutes=duration_minutes)
    return d.time()


def _weekday_monday_zero(d: date) -> int:
    """0=Monday .. 6=Sunday (matches Python weekday())."""
    return d.weekday()


async def _trainer_owns_arena(session: AsyncSession, trainer_id: int, arena_id: int) -> bool:
    r = await session.execute(
        text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
        {"tid": trainer_id, "aid": arena_id},
    )
    return r.fetchone() is not None


async def count_active_members(session: AsyncSession, training_group_id: int) -> int:
    r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int FROM training_group_members
            WHERE training_group_id = :gid AND status IN ('active', 'trial', 'waitlist')
            """
        ),
        {"gid": training_group_id},
    )
    return int(r.scalar() or 0)


async def count_seated_members(session: AsyncSession, training_group_id: int) -> int:
    """Active + trial (not waitlist)."""
    r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int FROM training_group_members
            WHERE training_group_id = :gid AND status IN (:a, :t)
            """
        ),
        {"gid": training_group_id, "a": MEMBER_ACTIVE, "t": MEMBER_TRIAL},
    )
    return int(r.scalar() or 0)


def _times_equal(a, b) -> bool:
    """Compare time values from DB/Python (ignore microseconds)."""
    if not hasattr(a, "hour"):
        return False
    if not hasattr(b, "hour"):
        return False
    return (a.hour, a.minute, a.second) == (b.hour, b.minute, b.second)


async def _fetch_slots_for_group_precheck(
    session: AsyncSession, trainer_id: int, start_d: date, end_d: date
) -> list:
    r = await session.execute(
        text(
            """
            SELECT s.id, s.slot_date, s.start_time, s.status, s.capacity, s.training_group_id, s.arena_id,
                   COALESCE(
                     (SELECT COUNT(*)::int FROM bookings b
                      WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')),
                     0
                   ) AS n_active_bookings
            FROM slots s
            WHERE s.trainer_id = :tid
              AND s.slot_date BETWEEN :sd AND :ed
              AND s.status != 'cancelled'
            """
        ),
        {"tid": trainer_id, "sd": start_d, "ed": end_d},
    )
    return list(r.fetchall())


async def _fetch_templates_for_group_precheck(session: AsyncSession, trainer_id: int) -> list:
    r = await session.execute(
        text(
            """
            SELECT id, day_of_week, start_time, duration_minutes, capacity, arena_id
            FROM trainer_schedule_templates
            WHERE trainer_id = :tid
            """
        ),
        {"tid": trainer_id},
    )
    return list(r.fetchall())


async def validate_training_group_schedule_before_create(
    session: AsyncSession,
    trainer_id: int,
    arena_id: int | None,
    schedule_rules: list[dict],
    season_start_date: date | None,
    *,
    weeks_ahead: int = SLOT_HORIZON_WEEKS,
) -> tuple[set[int], set[int]]:
    """
    Check new group rules against recurring clients, weekly templates, and concrete slots in the
    materialization window. Individual empty slots / capacity-1 template rows are returned for removal.

    Raises TrainingGroupScheduleConflictError when the operation must be blocked.
    """
    start_d, end_d = _materialize_date_range(season_start_date, weeks_ahead=weeks_ahead)
    slot_rows = await _fetch_slots_for_group_precheck(session, trainer_id, start_d, end_d)
    template_rows = await _fetch_templates_for_group_precheck(session, trainer_id)

    template_ids_to_delete: set[int] = set()
    slot_ids_to_delete: set[int] = set()

    for rule in schedule_rules:
        dow = int(rule["day_of_week"])
        st = _parse_rule_start_time(rule)

        r0 = await session.execute(
            text(
                """
                SELECT 1 FROM recurring_client_slots
                WHERE trainer_id = :tid AND day_of_week = :dow AND start_time = :st AND status = 'active'
                LIMIT 1
                """
            ),
            {"tid": trainer_id, "dow": dow, "st": st},
        )
        if r0.fetchone():
            raise TrainingGroupScheduleConflictError(
                "recurring",
                "На это время уже есть постоянное занятие клиента.",
            )

        for tr in template_rows:
            tid = int(tr[0])
            t_dow = int(tr[1])
            t_st = tr[2]
            cap = int(tr[4] or 1)
            t_arena = int(tr[5]) if tr[5] is not None else None
            if t_dow != dow or not _times_equal(t_st, st):
                continue
            if not _schedule_conflict_same_venue(t_arena, arena_id):
                continue
            if cap > 1:
                raise TrainingGroupScheduleConflictError(
                    "group_template",
                    "В шаблоне расписания уже есть групповое окно на это время.",
                )
            template_ids_to_delete.add(tid)

        d = start_d
        while d <= end_d:
            if d.weekday() != dow:
                d += timedelta(days=1)
                continue
            for row in slot_rows:
                sid = int(row[0])
                s_date = row[1]
                s_st = row[2]
                s_status = (row[3] or "").strip()
                s_cap = int(row[4] or 1)
                s_tgid = int(row[5]) if row[5] is not None else None
                s_arena = int(row[6]) if row[6] is not None else None
                n_book = int(row[7] or 0)
                if s_date != d:
                    continue
                if not _times_equal(s_st, st):
                    continue
                if not _schedule_conflict_same_venue(s_arena, arena_id):
                    continue

                if s_tgid is not None:
                    raise TrainingGroupScheduleConflictError(
                        "group_slot",
                        "На это время уже есть групповое занятие (другая группа).",
                    )
                if s_cap > 1:
                    raise TrainingGroupScheduleConflictError(
                        "group_slot",
                        "На это время уже есть групповое окно в расписании.",
                    )
                if s_status == "booked" or n_book > 0:
                    raise TrainingGroupScheduleConflictError(
                        "has_booking",
                        "Уже есть запись или активное бронирование на это время.",
                    )
                slot_ids_to_delete.add(sid)
            d += timedelta(days=1)

    return template_ids_to_delete, slot_ids_to_delete


async def validate_training_group_schedule_for_replace(
    session: AsyncSession,
    trainer_id: int,
    arena_id: int | None,
    schedule_rules: list[dict],
    season_start_date: date | None,
    *,
    exclude_training_group_id: int,
    weeks_ahead: int = SLOT_HORIZON_WEEKS,
) -> set[int]:
    """
    Same conflict checks as create, but:
    - weekly template rows (capacity 1) block the slot instead of being auto-removed;
    - concrete slots that belong to exclude_training_group_id are ignored (they will be cleared).
    Returns slot ids of empty individual slots to delete before materialization.
    """
    start_d, end_d = _materialize_date_range(season_start_date, weeks_ahead=weeks_ahead)
    slot_rows = await _fetch_slots_for_group_precheck(session, trainer_id, start_d, end_d)
    template_rows = await _fetch_templates_for_group_precheck(session, trainer_id)

    slot_ids_to_delete: set[int] = set()
    ex_gid = int(exclude_training_group_id)

    for rule in schedule_rules:
        dow = int(rule["day_of_week"])
        st = _parse_rule_start_time(rule)

        r0 = await session.execute(
            text(
                """
                SELECT 1 FROM recurring_client_slots
                WHERE trainer_id = :tid AND day_of_week = :dow AND start_time = :st AND status = 'active'
                LIMIT 1
                """
            ),
            {"tid": trainer_id, "dow": dow, "st": st},
        )
        if r0.fetchone():
            raise TrainingGroupScheduleConflictError(
                "recurring",
                "На это время уже есть постоянное занятие клиента.",
            )

        for tr in template_rows:
            t_dow = int(tr[1])
            t_st = tr[2]
            cap = int(tr[4] or 1)
            t_arena = int(tr[5]) if tr[5] is not None else None
            if t_dow != dow or not _times_equal(t_st, st):
                continue
            if not _schedule_conflict_same_venue(t_arena, arena_id):
                continue
            if cap > 1:
                raise TrainingGroupScheduleConflictError(
                    "group_template",
                    "В шаблоне расписания уже есть групповое окно на это время.",
                )
            raise TrainingGroupScheduleConflictError(
                "template",
                "На это время в шаблоне уже есть индивидуальный слот. Измените или удалите его в редакторе расписания.",
            )

        d = start_d
        while d <= end_d:
            if d.weekday() != dow:
                d += timedelta(days=1)
                continue
            for row in slot_rows:
                sid = int(row[0])
                s_date = row[1]
                s_st = row[2]
                s_status = (row[3] or "").strip()
                s_cap = int(row[4] or 1)
                s_tgid = int(row[5]) if row[5] is not None else None
                s_arena = int(row[6]) if row[6] is not None else None
                n_book = int(row[7] or 0)
                if s_date != d:
                    continue
                if not _times_equal(s_st, st):
                    continue
                if not _schedule_conflict_same_venue(s_arena, arena_id):
                    continue

                if s_tgid is not None and s_tgid == ex_gid:
                    continue

                if s_tgid is not None:
                    raise TrainingGroupScheduleConflictError(
                        "group_slot",
                        "На это время уже есть групповое занятие (другая группа).",
                    )
                if s_cap > 1:
                    raise TrainingGroupScheduleConflictError(
                        "group_slot",
                        "На это время уже есть групповое окно в расписании.",
                    )
                if s_status == "booked" or n_book > 0:
                    raise TrainingGroupScheduleConflictError(
                        "has_booking",
                        "Уже есть запись или активное бронирование на это время.",
                    )
                slot_ids_to_delete.add(sid)
            d += timedelta(days=1)

    return slot_ids_to_delete


async def _apply_individual_slot_removals(session: AsyncSession, trainer_id: int, slot_ids: set[int]) -> None:
    """Remove empty individual slots collected by validate_training_group_schedule_for_replace."""
    for sid in slot_ids:
        await session.execute(
            text(
                """
                DELETE FROM slots
                WHERE id = :sid AND trainer_id = :tid
                  AND training_group_id IS NULL
                  AND capacity = 1
                  AND status = 'available'
                  AND NOT EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.slot_id = slots.id AND b.status IN ('pending', 'confirmed')
                  )
                """
            ),
            {"sid": sid, "tid": trainer_id},
        )


async def has_future_group_slots_with_bookings(
    session: AsyncSession, trainer_id: int, training_group_id: int
) -> bool:
    """True if any future (>= today) non-cancelled group slot is booked or has active bookings."""
    r = await session.execute(
        text(
            """
            SELECT 1 FROM slots s
            WHERE s.training_group_id = :gid AND s.trainer_id = :tid
              AND s.slot_date >= CURRENT_DATE
              AND s.status != 'cancelled'
              AND (
                s.status = 'booked'
                OR EXISTS (
                  SELECT 1 FROM bookings b
                  WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')
                )
              )
            LIMIT 1
            """
        ),
        {"gid": training_group_id, "tid": trainer_id},
    )
    return r.fetchone() is not None


class TrainingGroupReplaceBlockedError(Exception):
    """Schedule replace blocked because future sessions have bookings."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


_UNSET = object()


async def replace_training_group_schedule(
    session: AsyncSession,
    trainer_id: int,
    training_group_id: int,
    *,
    schedule_rules: list[dict],
    season_start_date: date | None | object = _UNSET,
    service_id: int | None | object = _UNSET,
    arena_id: int | None | object = _UNSET,
) -> None:
    """
    Replace recurring rules and rematerialize slots. Blocks when future group slots have bookings.
    Optional service_id / arena_id / season_start_date: pass _UNSET to leave unchanged.
    """
    r0 = await session.execute(
        text(
            "SELECT status, service_id, arena_id, season_start_date FROM training_groups WHERE id = :gid AND trainer_id = :tid"
        ),
        {"gid": training_group_id, "tid": trainer_id},
    )
    row0 = r0.fetchone()
    if not row0:
        raise ValueError("Group not found")
    st, cur_sid, cur_aid, cur_ssd = row0[0], row0[1], row0[2], row0[3]
    if st == TG_ARCHIVED:
        raise TrainingGroupScheduleConflictError("archived", "Группа в архиве — расписание не меняется.")

    if await has_future_group_slots_with_bookings(session, trainer_id, training_group_id):
        raise TrainingGroupReplaceBlockedError(
            "Есть будущие занятия с записями. Перенесите или отмените брони, затем измените расписание серии."
        )

    if season_start_date is _UNSET:
        if cur_ssd is None:
            ssd = None
        elif isinstance(cur_ssd, datetime):
            ssd = cur_ssd.date()
        else:
            ssd = cur_ssd
    else:
        ssd = season_start_date  # type: ignore[assignment]

    eff_sid = int(cur_sid)
    if service_id is not _UNSET:
        eff_sid = int(service_id)  # type: ignore[arg-type]

    eff_aid: int | None = int(cur_aid) if cur_aid is not None else None
    if arena_id is not _UNSET:
        eff_aid = int(arena_id) if arena_id is not None else None  # type: ignore[arg-type]

    slot_ids = await validate_training_group_schedule_for_replace(
        session,
        trainer_id,
        eff_aid,
        schedule_rules,
        ssd,
        exclude_training_group_id=training_group_id,
    )
    await _apply_individual_slot_removals(session, trainer_id, slot_ids)
    await cancel_future_slots_for_group(session, trainer_id, training_group_id, do_commit=False)

    await session.execute(
        text("DELETE FROM training_group_schedule_rules WHERE training_group_id = :gid"),
        {"gid": training_group_id},
    )
    for rule in schedule_rules:
        dow = int(rule["day_of_week"])
        parts = str(rule["start_time"]).split(":")
        st_t = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
        dur = int(rule.get("duration_minutes") or 60)
        await session.execute(
            text(
                """
                INSERT INTO training_group_schedule_rules (training_group_id, day_of_week, start_time, duration_minutes)
                VALUES (:gid, :dow, :st, :dur)
                """
            ),
            {"gid": training_group_id, "dow": dow, "st": st_t, "dur": dur},
        )

    fields: list[str] = []
    params: dict = {"gid": training_group_id, "tid": trainer_id}
    if service_id is not _UNSET:
        fields.append("service_id = :sid")
        params["sid"] = eff_sid
    if arena_id is not _UNSET:
        fields.append("arena_id = :aid")
        params["aid"] = eff_aid
    if season_start_date is not _UNSET:
        fields.append("season_start_date = :ssd")
        params["ssd"] = ssd
    if fields:
        fields.append("updated_at = NOW()")
        await session.execute(
            text(f"UPDATE training_groups SET {', '.join(fields)} WHERE id = :gid AND trainer_id = :tid"),
            params,
        )

    # Single commit after rule replace + materialization (avoid half-applied schedule on materialize failure).
    await materialize_slots_for_group(session, trainer_id, training_group_id, do_commit=False, do_invalidate=False)
    await session.commit()
    invalidate_slots_for_trainer(trainer_id)


async def list_upcoming_group_slots(
    session: AsyncSession,
    trainer_id: int,
    training_group_id: int,
    *,
    limit: int = 20,
) -> list[dict]:
    """Concrete future slots for this cohort (for trainer UI)."""
    lim = max(1, min(int(limit), 100))
    r = await session.execute(
        text(
            """
            SELECT s.id, s.slot_date, s.start_time, s.end_time, s.status, s.capacity,
                   COALESCE(
                     (SELECT COUNT(*)::int FROM bookings b
                      WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')),
                     0
                   ) AS n_bookings
            FROM slots s
            WHERE s.training_group_id = :gid AND s.trainer_id = :tid
              AND s.status != 'cancelled'
              AND (
                s.slot_date > CURRENT_DATE
                OR (s.slot_date = CURRENT_DATE AND s.start_time >= CURRENT_TIME)
              )
            ORDER BY s.slot_date, s.start_time
            LIMIT :lim
            """
        ),
        {"gid": training_group_id, "tid": trainer_id, "lim": lim},
    )
    out: list[dict] = []
    for row in r.fetchall():
        sd, st_t, et = row[1], row[2], row[3]
        st_s = st_t.strftime("%H:%M") if hasattr(st_t, "strftime") else str(st_t)[:5]
        et_s = et.strftime("%H:%M") if hasattr(et, "strftime") else str(et)[:5]
        cap = max(1, int(row[5] or 1))
        out.append(
            {
                "id": int(row[0]),
                "slot_date": sd.isoformat() if hasattr(sd, "isoformat") else str(sd),
                "start_time": st_s,
                "end_time": et_s,
                "status": (row[4] or "").strip(),
                "capacity": cap,
                "active_bookings": int(row[6] or 0),
            }
        )
    return out


async def _apply_training_group_precheck_removals(
    session: AsyncSession,
    trainer_id: int,
    template_ids: set[int],
    slot_ids: set[int],
) -> None:
    """Remove replaceable template rows and empty individual slots before inserting the new group."""
    for tid in template_ids:
        await session.execute(
            text(
                "DELETE FROM trainer_schedule_templates WHERE id = :id AND trainer_id = :tid AND capacity = 1"
            ),
            {"id": tid, "tid": trainer_id},
        )
    for sid in slot_ids:
        await session.execute(
            text(
                """
                DELETE FROM slots
                WHERE id = :sid AND trainer_id = :tid
                  AND training_group_id IS NULL
                  AND capacity = 1
                  AND status = 'available'
                  AND NOT EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.slot_id = slots.id AND b.status IN ('pending', 'confirmed')
                  )
                """
            ),
            {"sid": sid, "tid": trainer_id},
        )


async def materialize_slots_for_group(
    session: AsyncSession,
    trainer_id: int,
    training_group_id: int,
    *,
    weeks_ahead: int = SLOT_HORIZON_WEEKS,
    do_commit: bool = True,
    do_invalidate: bool = True,
) -> int:
    """
    Insert future slots for all schedule rules. Skips dates that already have a slot for same start_time.
    Skips today's occurrences whose start time is already in the past (server local clock).
    Returns number of rows inserted.
    """
    r = await session.execute(
        text(
            """
            SELECT tg.id, tg.trainer_id, tg.service_id, tg.arena_id, tg.max_members, tg.season_start_date
            FROM training_groups tg WHERE tg.id = :gid AND tg.trainer_id = :tid
            """
        ),
        {"gid": training_group_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return 0
    _, _, service_id, arena_id, max_members, season_start = row
    cap = max(2, min(int(max_members), 500))
    svc = int(service_id)
    aid = int(arena_id) if arena_id is not None else None

    r2 = await session.execute(
        text(
            """
            SELECT day_of_week, start_time, duration_minutes
            FROM training_group_schedule_rules WHERE training_group_id = :gid
            ORDER BY day_of_week, start_time
            """
        ),
        {"gid": training_group_id},
    )
    rules = r2.fetchall()
    if not rules:
        return 0

    start_d, end_d = _materialize_date_range(season_start, weeks_ahead=weeks_ahead)
    now = datetime.now()

    created = 0
    d = start_d
    while d <= end_d:
        dow = _weekday_monday_zero(d)
        for day_w, st_raw, dur_raw in rules:
            if int(day_w) != dow:
                continue
            if hasattr(st_raw, "hour"):
                st = st_raw
            else:
                parts = str(st_raw).split(":")
                st = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            dur = int(dur_raw or 60)
            # Do not materialize a same-day slot whose start has already passed (avoids useless past rows).
            if d == now.date() and datetime.combine(d, st) < now:
                continue
            end_t = _time_end(st, dur)
            # Avoid asyncpg "ambiguous parameter" when :aid is NULL — branch explicitly.
            if aid is None:
                ex = await session.execute(
                    text(
                        """
                        SELECT 1 FROM slots
                        WHERE trainer_id = :tid AND slot_date = :d AND start_time = :st
                          AND status != 'cancelled'
                        """
                    ),
                    {"tid": trainer_id, "d": d, "st": st},
                )
            else:
                ex = await session.execute(
                    text(
                        """
                        SELECT 1 FROM slots
                        WHERE trainer_id = :tid AND slot_date = :d AND start_time = :st
                          AND status != 'cancelled'
                          AND (arena_id IS NULL OR arena_id = :aid)
                        """
                    ),
                    {"tid": trainer_id, "d": d, "st": st, "aid": aid},
                )
            if ex.fetchone():
                continue
            await session.execute(
                text(
                    """
                    INSERT INTO slots (
                        trainer_id, slot_date, start_time, end_time, status, capacity,
                        service_id, arena_id, training_group_id
                    )
                    VALUES (:tid, :d, :st, :et, 'available', :cap, :svc, :aid, :gid)
                """
                ),
                {
                    "tid": trainer_id,
                    "d": d,
                    "st": st,
                    "et": end_t,
                    "cap": cap,
                    "svc": svc,
                    "aid": aid,
                    "gid": training_group_id,
                },
            )
            created += 1
        d += timedelta(days=1)

    if do_commit:
        await session.commit()
    if do_invalidate:
        invalidate_slots_for_trainer(trainer_id)
    return created


async def update_future_group_slot_capacities(session: AsyncSession, trainer_id: int, training_group_id: int) -> None:
    r = await session.execute(
        text("SELECT max_members FROM training_groups WHERE id = :gid AND trainer_id = :tid"),
        {"gid": training_group_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return
    cap = max(2, min(int(row[0]), 500))
    # Align cohort slot capacity with roster limit; do not shrink booked slots below current headcount.
    await session.execute(
        text(
            """
            UPDATE slots AS s SET capacity = :cap
            WHERE s.training_group_id = :gid AND s.trainer_id = :tid AND s.slot_date >= CURRENT_DATE
              AND s.status != 'cancelled'
              AND (
                s.status = 'available'
                OR COALESCE(
                     (SELECT COUNT(*)::int FROM bookings b
                      WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')),
                     0
                   ) <= :cap
              )
            """
        ),
        {"cap": cap, "gid": training_group_id, "tid": trainer_id},
    )
    await session.commit()
    invalidate_slots_for_trainer(trainer_id)


async def cancel_future_slots_for_group(
    session: AsyncSession,
    trainer_id: int,
    training_group_id: int,
    *,
    do_commit: bool = True,
) -> None:
    """Cancel future group slots that have no active bookings (MVP)."""
    await session.execute(
        text(
            """
            UPDATE slots SET status = 'cancelled'
            WHERE training_group_id = :gid AND trainer_id = :tid AND slot_date >= CURRENT_DATE
              AND status = 'available'
              AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.slot_id = slots.id AND b.status IN ('pending', 'confirmed')
              )
            """
        ),
        {"gid": training_group_id, "tid": trainer_id},
    )
    if do_commit:
        await session.commit()
        invalidate_slots_for_trainer(trainer_id)


async def cancel_group_slot(
    session: AsyncSession, trainer_id: int, training_group_id: int, slot_id: int
) -> bool:
    """Cancel one future empty group slot. False if not found or has bookings."""
    r = await session.execute(
        text(
            """
            UPDATE slots SET status = 'cancelled'
            WHERE id = :sid AND trainer_id = :tid AND training_group_id = :gid
              AND slot_date >= CURRENT_DATE
              AND status = 'available'
              AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.slot_id = slots.id AND b.status IN ('pending', 'confirmed')
              )
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "gid": training_group_id},
    )
    ok = r.fetchone() is not None
    if ok:
        await session.commit()
        invalidate_slots_for_trainer(trainer_id)
    return ok


async def cancel_future_group_slots_in_range(
    session: AsyncSession,
    trainer_id: int,
    training_group_id: int,
    date_from: date,
    date_to: date,
) -> int:
    """Cancel empty group slots in [date_from, date_to] (inclusive). Returns number of rows updated."""
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    r = await session.execute(
        text(
            """
            UPDATE slots SET status = 'cancelled'
            WHERE training_group_id = :gid AND trainer_id = :tid
              AND slot_date >= CURRENT_DATE
              AND slot_date BETWEEN :df AND :dt
              AND status = 'available'
              AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.slot_id = slots.id AND b.status IN ('pending', 'confirmed')
              )
            """
        ),
        {"gid": training_group_id, "tid": trainer_id, "df": date_from, "dt": date_to},
    )
    n = r.rowcount if hasattr(r, "rowcount") else 0
    await session.commit()
    invalidate_slots_for_trainer(trainer_id)
    return int(n or 0)


async def list_training_groups(session: AsyncSession, trainer_id: int) -> list[dict]:
    r = await session.execute(
        text(
            """
            SELECT tg.id, tg.name, tg.service_id, s.name, tg.arena_id, a.name,
                   tg.max_members, tg.status, tg.catalog_visible, tg.season_start_date,
                   tg.created_at,
                   (SELECT COUNT(*)::int FROM training_group_members m
                    WHERE m.training_group_id = tg.id AND m.status IN ('active', 'trial', 'waitlist')) AS member_count
            FROM training_groups tg
            JOIN services s ON s.id = tg.service_id
            LEFT JOIN arenas a ON a.id = tg.arena_id
            WHERE tg.trainer_id = :tid
            ORDER BY tg.updated_at DESC, tg.id DESC
            """
        ),
        {"tid": trainer_id},
    )
    rows = r.fetchall()
    out = []
    for row in rows:
        gid = int(row[0])
        next_dt = await _next_session_datetime(session, trainer_id, gid)
        out.append(
            {
                "id": gid,
                "name": row[1],
                "service_id": int(row[2]),
                "service_name": (row[3] or "").strip() or "—",
                "arena_id": int(row[4]) if row[4] is not None else None,
                "arena_name": (row[5] or "").strip() if row[5] else None,
                "max_members": int(row[6]),
                "status": row[7],
                "catalog_visible": bool(row[8]),
                "season_start_date": row[9].isoformat() if row[9] else None,
                "created_at": row[10].isoformat() if row[10] else None,
                "member_count": int(row[11] or 0),
                "next_session_at": next_dt,
            }
        )
    return out


async def _next_session_datetime(session: AsyncSession, trainer_id: int, training_group_id: int) -> str | None:
    r = await session.execute(
        text(
            """
            SELECT slot_date, start_time FROM slots
            WHERE trainer_id = :tid AND training_group_id = :gid AND status != 'cancelled'
              AND (slot_date > CURRENT_DATE OR (slot_date = CURRENT_DATE AND start_time >= CURRENT_TIME))
            ORDER BY slot_date, start_time
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "gid": training_group_id},
    )
    row = r.fetchone()
    if not row:
        return None
    sd, st = row[0], row[1]
    st_s = st.strftime("%H:%M") if hasattr(st, "strftime") else str(st)[:5]
    if hasattr(sd, "isoformat"):
        return f"{sd.isoformat()}T{st_s}"
    return f"{sd}T{st_s}"


async def get_training_group_detail(session: AsyncSession, trainer_id: int, group_id: int) -> dict | None:
    r = await session.execute(
        text(
            """
            SELECT tg.id, tg.name, tg.service_id, s.name, tg.arena_id, a.name,
                   tg.max_members, tg.status, tg.catalog_visible, tg.catalog_pitch, tg.season_start_date,
                   tg.created_at, tg.updated_at
            FROM training_groups tg
            JOIN services s ON s.id = tg.service_id
            LEFT JOIN arenas a ON a.id = tg.arena_id
            WHERE tg.id = :gid AND tg.trainer_id = :tid
            """
        ),
        {"gid": group_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    rules_r = await session.execute(
        text(
            """
            SELECT id, day_of_week, start_time, duration_minutes
            FROM training_group_schedule_rules WHERE training_group_id = :gid
            ORDER BY day_of_week, start_time
            """
        ),
        {"gid": group_id},
    )
    rules = []
    for rr in rules_r.fetchall():
        st = rr[2]
        rules.append(
            {
                "id": int(rr[0]),
                "day_of_week": int(rr[1]),
                "start_time": st.strftime("%H:%M") if hasattr(st, "strftime") else str(st)[:5],
                "duration_minutes": int(rr[3]),
            }
        )
    members_r = await session.execute(
        text(
            """
            SELECT m.client_id, m.status, c.first_name, c.last_name, c.phone
            FROM training_group_members m
            JOIN clients c ON c.id = m.client_id
            WHERE m.training_group_id = :gid
            ORDER BY m.created_at ASC
            """
        ),
        {"gid": group_id},
    )
    members = []
    for mr in members_r.fetchall():
        members.append(
            {
                "client_id": int(mr[0]),
                "status": mr[1],
                "first_name": mr[2],
                "last_name": mr[3],
                "phone": mr[4],
            }
        )
    seated = await count_seated_members(session, group_id)
    return {
        "id": int(row[0]),
        "name": row[1],
        "service_id": int(row[2]),
        "service_name": (row[3] or "").strip() or "—",
        "arena_id": int(row[4]) if row[4] is not None else None,
        "arena_name": (row[5] or "").strip() if row[5] else None,
        "max_members": int(row[6]),
        "status": row[7],
        "catalog_visible": bool(row[8]),
        "catalog_pitch": row[9],
        "season_start_date": row[10].isoformat() if row[10] else None,
        "created_at": row[11].isoformat() if row[11] else None,
        "updated_at": row[12].isoformat() if row[12] else None,
        "schedule_rules": rules,
        "members": members,
        "seated_count": seated,
        "spots_left": max(0, int(row[6]) - seated),
        "next_session_at": await _next_session_datetime(session, trainer_id, group_id),
    }


async def create_training_group(
    session: AsyncSession,
    trainer_id: int,
    *,
    name: str,
    service_id: int,
    arena_id: int | None,
    max_members: int,
    status: str,
    season_start_date: date | None,
    catalog_visible: bool,
    catalog_pitch: str | None,
    schedule_rules: list[dict],  # {day_of_week, start_time str HH:MM, duration_minutes}
) -> int:
    """Insert group + rules; materialize slots. Returns group id."""
    template_ids, slot_ids = await validate_training_group_schedule_before_create(
        session, trainer_id, arena_id, schedule_rules, season_start_date
    )
    await _apply_training_group_precheck_removals(session, trainer_id, template_ids, slot_ids)

    cap = max(2, min(int(max_members), 500))
    r = await session.execute(
        text(
            """
            INSERT INTO training_groups (
                trainer_id, name, service_id, arena_id, max_members, status,
                season_start_date, catalog_visible, catalog_pitch
            )
            VALUES (:tid, :name, :sid, :aid, :cap, :st, :ssd, :cv, :cp)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "name": (name or "").strip()[:200],
            "sid": service_id,
            "aid": arena_id,
            "cap": cap,
            "st": status,
            "ssd": season_start_date,
            "cv": catalog_visible,
            "cp": (catalog_pitch or "").strip() or None,
        },
    )
    (gid,) = r.fetchone()
    gid = int(gid)
    for rule in schedule_rules:
        dow = int(rule["day_of_week"])
        parts = str(rule["start_time"]).split(":")
        st = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
        dur = int(rule.get("duration_minutes") or 60)
        await session.execute(
            text(
                """
                INSERT INTO training_group_schedule_rules (training_group_id, day_of_week, start_time, duration_minutes)
                VALUES (:gid, :dow, :st, :dur)
                """
            ),
            {"gid": gid, "dow": dow, "st": st, "dur": dur},
        )
    await materialize_slots_for_group(session, trainer_id, gid)
    from src.application.trainer_feature_tracking import FEATURE_GROUP_CREATED, record_feature_first_use

    await record_feature_first_use(session, trainer_id, FEATURE_GROUP_CREATED)
    return gid


async def _resume_status_after_paused(
    session: AsyncSession,
    trainer_id: int,
    group_id: int,
    season_start: date | None,
) -> str:
    """
    Resume from paused: UI used to always request 'active', which wrongly ended recruitment
    before season_start / first session. Prefer 'recruiting' until the calendar season starts
    or until the first slot day is still strictly in the future.
    """
    today = date.today()
    if season_start is not None and season_start > today:
        return TG_RECRUITING
    r = await session.execute(
        text(
            """
            SELECT MIN(slot_date)
            FROM slots
            WHERE trainer_id = :tid AND training_group_id = :gid AND status != 'cancelled'
              AND slot_date >= CURRENT_DATE
            """
        ),
        {"tid": trainer_id, "gid": group_id},
    )
    row = r.fetchone()
    fd = row[0] if row else None
    if fd is not None and fd > today:
        return TG_RECRUITING
    return TG_ACTIVE


async def update_training_group(
    session: AsyncSession,
    trainer_id: int,
    group_id: int,
    *,
    name: str | None = None,
    max_members: int | None = None,
    status: str | None = None,
    catalog_visible: bool | None = None,
    catalog_pitch: str | None = None,
    season_start_date: date | None = None,
) -> bool:
    fields: list[str] = []
    params: dict = {"gid": group_id, "tid": trainer_id}
    if name is not None:
        fields.append("name = :name")
        params["name"] = name.strip()[:200]
    if max_members is not None:
        fields.append("max_members = :mm")
        params["mm"] = max(2, min(int(max_members), 500))
    if status is not None:
        # Paused → active (resume): never force active while season/first slot is still ahead.
        r0 = await session.execute(
            text(
                "SELECT status, season_start_date FROM training_groups WHERE id = :gid AND trainer_id = :tid"
            ),
            {"gid": group_id, "tid": trainer_id},
        )
        cur = r0.fetchone()
        if cur and cur[0] == TG_PAUSED and status == TG_ACTIVE:
            ssd = cur[1]
            if isinstance(ssd, datetime):
                ssd = ssd.date()
            status = await _resume_status_after_paused(session, trainer_id, group_id, ssd)
        fields.append("status = :st")
        params["st"] = status
    if catalog_visible is not None:
        fields.append("catalog_visible = :cv")
        params["cv"] = catalog_visible
    if catalog_pitch is not None:
        fields.append("catalog_pitch = :cp")
        params["cp"] = catalog_pitch.strip() or None
    if season_start_date is not None:
        fields.append("season_start_date = :ssd")
        params["ssd"] = season_start_date
    if not fields:
        return True
    fields.append("updated_at = NOW()")
    q = f"UPDATE training_groups SET {', '.join(fields)} WHERE id = :gid AND trainer_id = :tid RETURNING id"
    r = await session.execute(text(q), params)
    ok = r.fetchone() is not None
    await session.commit()
    if not ok:
        return False
    if max_members is not None:
        await update_future_group_slot_capacities(session, trainer_id, group_id)
    if status == TG_ARCHIVED:
        await cancel_future_slots_for_group(session, trainer_id, group_id)
    invalidate_slots_for_trainer(trainer_id)
    return True


async def add_group_member(
    session: AsyncSession,
    trainer_id: int,
    group_id: int,
    client_id: int,
    *,
    status: str = MEMBER_ACTIVE,
    do_commit: bool = True,
    expand_roster: bool = False,
) -> bool:
    r = await session.execute(
        text("SELECT id, max_members, status FROM training_groups WHERE id = :gid AND trainer_id = :tid"),
        {"gid": group_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row or row[2] == TG_ARCHIVED:
        return False
    max_m = int(row[1])
    seated = await count_seated_members(session, group_id)
    roster_expanded = False
    if status in (MEMBER_ACTIVE, MEMBER_TRIAL) and seated >= max_m:
        if not expand_roster:
            return False
        roster_expanded = True
        new_max = max(2, min(max_m + 1, 500))
        await session.execute(
            text(
                "UPDATE training_groups SET max_members = :nm, updated_at = NOW() "
                "WHERE id = :gid AND trainer_id = :tid"
            ),
            {"nm": new_max, "gid": group_id, "tid": trainer_id},
        )
        # Keep cohort slot capacity aligned with roster (future sessions, non-cancelled).
        await session.execute(
            text(
                """
                UPDATE slots SET capacity = :cap
                WHERE training_group_id = :gid AND trainer_id = :tid
                  AND slot_date >= CURRENT_DATE
                  AND status != 'cancelled'
                """
            ),
            {"cap": new_max, "gid": group_id, "tid": trainer_id},
        )
    await session.execute(
        text(
            """
            INSERT INTO training_group_members (training_group_id, client_id, status)
            VALUES (:gid, :cid, :st)
            ON CONFLICT (training_group_id, client_id) DO UPDATE SET status = EXCLUDED.status
            """
        ),
        {"gid": group_id, "cid": client_id, "st": status},
    )
    if do_commit:
        await session.commit()
    if roster_expanded:
        invalidate_slots_for_trainer(trainer_id)
    return True


async def remove_group_member(session: AsyncSession, trainer_id: int, group_id: int, client_id: int) -> bool:
    from src.application.group_attendance_use_cases import skip_attendance_prompts_for_removed_member

    await skip_attendance_prompts_for_removed_member(session, group_id, client_id, do_commit=False)
    r = await session.execute(
        text(
            """
            DELETE FROM training_group_members m
            USING training_groups tg
            WHERE m.training_group_id = tg.id AND tg.trainer_id = :tid
              AND m.training_group_id = :gid AND m.client_id = :cid
            RETURNING m.id
            """
        ),
        {"tid": trainer_id, "gid": group_id, "cid": client_id},
    )
    ok = r.fetchone() is not None
    if ok:
        await session.commit()
    return ok


async def list_pending_join_requests(session: AsyncSession, trainer_id: int, group_id: int) -> list[dict]:
    r = await session.execute(
        text(
            """
            SELECT j.id, j.client_id, j.status, j.created_at, c.first_name, c.last_name, c.phone
            FROM training_group_join_requests j
            JOIN training_groups tg ON tg.id = j.training_group_id
            JOIN clients c ON c.id = j.client_id
            WHERE tg.trainer_id = :tid AND j.training_group_id = :gid AND j.status = 'pending'
            ORDER BY j.created_at ASC
            """
        ),
        {"tid": trainer_id, "gid": group_id},
    )
    out = []
    for row in r.fetchall():
        out.append(
            {
                "id": int(row[0]),
                "client_id": int(row[1]),
                "status": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
                "first_name": row[4],
                "last_name": row[5],
                "phone": row[6],
            }
        )
    return out


async def approve_join_request(session: AsyncSession, trainer_id: int, group_id: int, request_id: int) -> bool:
    r = await session.execute(
        text(
            """
            SELECT j.id, j.client_id FROM training_group_join_requests j
            JOIN training_groups tg ON tg.id = j.training_group_id
            WHERE j.id = :rid AND j.training_group_id = :gid AND tg.trainer_id = :tid AND j.status = 'pending'
            """
        ),
        {"rid": request_id, "gid": group_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return False
    client_id = int(row[1])
    if not await add_group_member(
        session, trainer_id, group_id, client_id, status=MEMBER_ACTIVE, do_commit=False
    ):
        await session.rollback()
        return False
    await session.execute(
        text("UPDATE training_group_join_requests SET status = :st WHERE id = :rid"),
        {"st": JOIN_APPROVED, "rid": request_id},
    )
    await session.commit()
    return True


async def reject_join_request(session: AsyncSession, trainer_id: int, group_id: int, request_id: int) -> bool:
    r = await session.execute(
        text(
            """
            UPDATE training_group_join_requests SET status = :st
            WHERE id = :rid AND training_group_id = :gid AND status = 'pending'
              AND EXISTS (
                SELECT 1 FROM training_groups tg
                WHERE tg.id = training_group_join_requests.training_group_id AND tg.trainer_id = :tid
              )
            RETURNING id
            """
        ),
        {"st": JOIN_REJECTED, "rid": request_id, "gid": group_id, "tid": trainer_id},
    )
    ok = r.fetchone() is not None
    if ok:
        await session.commit()
    return ok


async def client_request_join_group(
    session: AsyncSession, training_group_id: int, client_id: int
) -> tuple[bool, str | None]:
    """
    Client applies from catalog: enroll immediately (no trainer approval).
    Returns (ok, error_code). error_code: not_found, not_recruiting, full, duplicate
    """
    r = await session.execute(
        text(
            """
            SELECT tg.id, tg.trainer_id, tg.status, tg.max_members, tg.catalog_visible
            FROM training_groups tg
            WHERE tg.id = :gid
            """
        ),
        {"gid": training_group_id},
    )
    row = r.fetchone()
    if not row:
        return False, "not_found"
    trainer_id = int(row[1])
    status, max_m, vis = row[2], int(row[3]), bool(row[4])
    if status != TG_RECRUITING or not vis:
        return False, "not_recruiting"
    seated = await count_seated_members(session, training_group_id)
    rdup = await session.execute(
        text(
            """
            SELECT 1 FROM training_group_members WHERE training_group_id = :gid AND client_id = :cid
            AND status IN (:a, :t, :w)
            """
        ),
        {"gid": training_group_id, "cid": client_id, "a": MEMBER_ACTIVE, "t": MEMBER_TRIAL, "w": MEMBER_WAITLIST},
    )
    if rdup.fetchone():
        return False, "duplicate"
    if seated >= max_m:
        return False, "full"
    # Drop legacy pending row (if any), then add to roster in one transaction.
    await session.execute(
        text(
            """
            DELETE FROM training_group_join_requests
            WHERE training_group_id = :gid AND client_id = :cid AND status = 'pending'
            """
        ),
        {"gid": training_group_id, "cid": client_id},
    )
    if not await add_group_member(
        session, trainer_id, training_group_id, client_id, status=MEMBER_ACTIVE, do_commit=False
    ):
        await session.rollback()
        return False, "full"
    await session.commit()
    return True, None


async def list_open_training_groups_public(session: AsyncSession, trainer_id: int) -> list[dict]:
    """Catalog: recruiting + visible + has free seats (by seated count)."""
    r = await session.execute(
        text(
            """
            SELECT tg.id, tg.name, tg.service_id, s.name, tg.arena_id, a.name,
                   tg.max_members, tg.catalog_pitch,
                   (SELECT COUNT(*)::int FROM training_group_members m
                    WHERE m.training_group_id = tg.id AND m.status IN ('active', 'trial')) AS seated
            FROM training_groups tg
            JOIN trainers tr ON tr.id = tg.trainer_id AND tr.status = 'active' AND tr.is_catalog_visible = true
            JOIN services s ON s.id = tg.service_id
            LEFT JOIN arenas a ON a.id = tg.arena_id
            WHERE tg.trainer_id = :tid AND tg.status = :st AND tg.catalog_visible = true
            """
        ),
        {"tid": trainer_id, "st": TG_RECRUITING},
    )
    out = []
    for row in r.fetchall():
        max_m = int(row[6])
        seated = int(row[8] or 0)
        if seated >= max_m:
            continue
        gid = int(row[0])
        rules_r = await session.execute(
            text(
                """
                SELECT day_of_week, start_time, duration_minutes
                FROM training_group_schedule_rules WHERE training_group_id = :gid
                ORDER BY day_of_week, start_time
                """
            ),
            {"gid": gid},
        )
        rules = []
        for rr in rules_r.fetchall():
            st = rr[1]
            rules.append(
                {
                    "day_of_week": int(rr[0]),
                    "start_time": st.strftime("%H:%M") if hasattr(st, "strftime") else str(st)[:5],
                    "duration_minutes": int(rr[2]),
                }
            )
        out.append(
            {
                "id": gid,
                "name": row[1],
                "service_id": int(row[2]),
                "service_name": (row[3] or "").strip() or "—",
                "arena_id": int(row[4]) if row[4] is not None else None,
                "arena_name": (row[5] or "").strip() if row[5] else None,
                "max_members": max_m,
                "catalog_pitch": row[7],
                "seated_count": seated,
                "spots_left": max(0, max_m - seated),
                "schedule_rules": rules,
            }
        )
    return out


async def get_group_public_preview(session: AsyncSession, trainer_id: int, group_id: int) -> dict | None:
    """Single group for catalog if visible and recruiting."""
    rows = await list_open_training_groups_public(session, trainer_id)
    for g in rows:
        if g["id"] == group_id:
            return g
    return None


_RATING_PRIOR_M = 10.0
_RATING_PRIOR_C = 4.0


async def list_open_training_groups_catalog(
    session: AsyncSession,
    *,
    city_id: int | None = None,
    service_id: int | None = None,
    arena_id: int | None = None,
    arena_ids: list[int] | None = None,
    filter_days: list[int] | None = None,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Cross-trainer catalog: open recruiting groups with free roster seats.
    Same business rules as list_open_training_groups_public per group, plus city/service/arena filters.

    arena_ids semantics — show a group if its venue (or, when group has no venue, the trainer)
    matches **any** of the selected arenas. arena_id is a legacy alias and is promoted to
    arena_ids=[arena_id] when arena_ids is empty.
    """
    lim = max(1, min(int(limit), 100))
    off = max(0, int(offset))
    days = [int(d) for d in (filter_days or []) if 0 <= int(d) <= 6]
    has_day_filter = bool(days)

    # Normalize legacy single-id alias.
    effective_arena_ids: list[int] | None = None
    if arena_ids:
        effective_arena_ids = list({int(a) for a in arena_ids if a is not None})
    elif arena_id is not None:
        effective_arena_ids = [int(arena_id)]
    if effective_arena_ids is not None and not effective_arena_ids:
        effective_arena_ids = None

    params: dict = {
        "st": TG_RECRUITING,
        "m": _RATING_PRIOR_M,
        "c": _RATING_PRIOR_C,
        "lim": lim,
        "off": off,
    }

    day_clause = ""
    if has_day_filter:
        placeholders = ", ".join(f":dow{i}" for i in range(len(days)))
        for i, d in enumerate(days):
            params[f"dow{i}"] = d
        day_clause = f"""
          AND EXISTS (
            SELECT 1 FROM training_group_schedule_rules r
            WHERE r.training_group_id = tg.id AND r.day_of_week IN ({placeholders})
          )
        """

    # Optional filters — avoid `param IS NULL` (asyncpg ambiguous types); omit clause when unset.
    filter_parts: list[str] = []
    if city_id is not None:
        filter_parts.append("p.city_id = :city_id")
        params["city_id"] = int(city_id)
    if service_id is not None:
        filter_parts.append("tg.service_id = :service_id")
        params["service_id"] = int(service_id)
    if effective_arena_ids is not None:
        arena_phs = ", ".join(f":arena_id_{i}" for i in range(len(effective_arena_ids)))
        for i, a in enumerate(effective_arena_ids):
            params[f"arena_id_{i}"] = a
        filter_parts.append(
            f"""(
          tg.arena_id IN ({arena_phs})
          OR (
            tg.arena_id IS NULL
            AND EXISTS (
              SELECT 1 FROM trainer_arenas ta
              WHERE ta.trainer_id = tg.trainer_id AND ta.arena_id IN ({arena_phs})
            )
          )
        )"""
        )
    filter_sql = ""
    if filter_parts:
        filter_sql = " AND " + " AND ".join(filter_parts)

    base_from = f"""
      FROM training_groups tg
      JOIN trainers t ON t.id = tg.trainer_id AND t.status = 'active' AND t.is_catalog_visible = true
      JOIN trainer_profiles p ON p.trainer_id = t.id
      JOIN services srv ON srv.id = tg.service_id
      LEFT JOIN arenas ar ON ar.id = tg.arena_id
      WHERE tg.status = :st AND tg.catalog_visible = true
        AND EXISTS (
          SELECT 1 FROM trainer_subscriptions ts
          WHERE ts.trainer_id = t.id
            AND ts.expires_at > NOW() AND ts.status IN ('trial', 'active')
        )
        {filter_sql}
        AND (
          SELECT COUNT(*)::int FROM training_group_members m
          WHERE m.training_group_id = tg.id AND m.status IN ('active', 'trial')
        ) < tg.max_members
        {day_clause}
    """

    count_q = text(f"SELECT COUNT(*)::int {base_from}")
    r_cnt = await session.execute(count_q, params)
    total = int(r_cnt.scalar() or 0)

    score_sql = f"""
      SELECT tg.id, tg.trainer_id, tg.name, tg.service_id, srv.name AS service_name,
             tg.arena_id, ar.name AS arena_name, tg.max_members, tg.catalog_pitch,
             (SELECT COUNT(*)::int FROM training_group_members m
              WHERE m.training_group_id = tg.id AND m.status IN ('active', 'trial')) AS seated,
             p.first_name, p.last_name,
             (
               (COALESCE(p.rating_count, 0)::float / (COALESCE(p.rating_count, 0) + :m))
               * COALESCE(p.rating_avg, 0.0)::float
               + (
                 (CAST(:m AS double precision) / (COALESCE(p.rating_count, 0) + :m))
                 * CAST(:c AS double precision)
               )
             ) AS _score
      {base_from}
      ORDER BY _score DESC NULLS LAST, tg.id
      LIMIT :lim OFFSET :off
    """
    r = await session.execute(text(score_sql), params)
    rows = r.fetchall()
    if not rows:
        return [], total

    group_ids = [int(row[0]) for row in rows]
    ph = ", ".join(f":gid{i}" for i in range(len(group_ids)))
    for i, gid in enumerate(group_ids):
        params[f"gid{i}"] = gid
    rules_r = await session.execute(
        text(
            f"""
            SELECT training_group_id, day_of_week, start_time, duration_minutes
            FROM training_group_schedule_rules
            WHERE training_group_id IN ({ph})
            ORDER BY training_group_id, day_of_week, start_time
            """
        ),
        params,
    )
    rules_by_gid: dict[int, list[dict]] = {}
    for rr in rules_r.fetchall():
        gid = int(rr[0])
        st = rr[2]
        rules_by_gid.setdefault(gid, []).append(
            {
                "day_of_week": int(rr[1]),
                "start_time": st.strftime("%H:%M") if hasattr(st, "strftime") else str(st)[:5],
                "duration_minutes": int(rr[3]),
            }
        )

    # Columns: 0 id, 1 trainer_id, 2 name, 3 service_id, 4 service_name, 5 arena_id, 6 arena_name,
    # 7 max_members, 8 catalog_pitch, 9 seated, 10 first_name, 11 last_name, 12 _score
    out: list[dict] = []
    for row in rows:
        gid = int(row[0])
        tid = int(row[1])
        max_m = int(row[7])
        seated = int(row[9] or 0)
        rules = rules_by_gid.get(gid, [])
        out.append(
            {
                "id": gid,
                "trainer_id": tid,
                "name": row[2],
                "service_id": int(row[3]),
                "service_name": (row[4] or "").strip() or "—",
                "arena_id": int(row[5]) if row[5] is not None else None,
                "arena_name": (row[6] or "").strip() if row[6] else None,
                "max_members": max_m,
                "catalog_pitch": row[8],
                "seated_count": seated,
                "spots_left": max(0, max_m - seated),
                "schedule_rules": rules,
                "trainer": {
                    "id": tid,
                    "profile": {
                        "first_name": row[10],
                        "last_name": row[11],
                    },
                },
            }
        )
    return out, total


async def batch_open_groups_count_for_trainers(
    session: AsyncSession, trainer_ids: list[int]
) -> dict[int, int]:
    """How many catalog-open groups (recruiting, visible, roster has space) per trainer."""
    if not trainer_ids:
        return {}
    placeholders = ", ".join(f":tid{i}" for i in range(len(trainer_ids)))
    params: dict = {f"tid{i}": v for i, v in enumerate(trainer_ids)}
    params["st"] = TG_RECRUITING
    r = await session.execute(
        text(
            f"""
            SELECT tg.trainer_id, COUNT(*)::int
            FROM training_groups tg
            JOIN trainers t ON t.id = tg.trainer_id AND t.status = 'active' AND t.is_catalog_visible = true
            WHERE tg.trainer_id IN ({placeholders})
              AND tg.status = :st AND tg.catalog_visible = true
              AND (
                SELECT COUNT(*)::int FROM training_group_members m
                WHERE m.training_group_id = tg.id AND m.status IN ('active', 'trial')
              ) < tg.max_members
            GROUP BY tg.trainer_id
            """
        ),
        params,
    )
    return {int(row[0]): int(row[1]) for row in r.fetchall()}
