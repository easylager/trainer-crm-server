"""
Recurring client slots (fixed weekly time) and wait-for-slot requests.
Clean separation: domain rules here; booking/slot creation delegated to booking_use_cases and schedule.
"""
from datetime import date, time, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    _booking_interval_duration_minutes,
    create_booking,
    get_first_service_id_for_trainer,
    is_slot_start_in_past_local,
)
from src.application.trainer_schedule_use_cases import (
    ensure_individual_slot_for_quick_book,
    next_week_monday,
    this_week_monday,
)

RECURRING_STATUS_ACTIVE = "active"
RECURRING_STATUS_PAUSED = "paused"
RECURRING_STATUS_CANCELLED = "cancelled"

# Monday = 0 (Python weekday); short RU labels for trainer UI.
RECURRING_WEEKDAY_SHORT_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _format_time_hhmm(t: object) -> str:
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")  # type: ignore[union-attr]
    s = str(t)
    return s[:5] if len(s) >= 5 else s


def _parse_hhmm_string(s: object) -> time | None:
    raw = str(s or "").strip()
    if len(raw) >= 4 and ":" in raw:
        try:
            parts = raw.split(":")
            return time(int(parts[0]), int(parts[1]))
        except (TypeError, ValueError, IndexError):
            return None
    return _coerce_to_time(s)


def _coerce_to_time(v: object) -> time | None:
    """Normalize DB/ORM time-like values for recurring rule lookup."""
    if isinstance(v, time):
        return v
    if hasattr(v, "hour") and hasattr(v, "minute"):
        try:
            return time(int(v.hour), int(v.minute), int(getattr(v, "second", 0) or 0))
        except (TypeError, ValueError):
            return None
    return None


async def list_recurring_booking_suggestions_for_trainer_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Cards for «make weekly recurring» from client history, with active-rule id if any.
    History is ordered newest-first; we keep one row per (weekday, start time, service, arena) —
    the chronologically nearest occurrence (first in that order). ``limit`` caps unique patterns (max 10).
    """
    from src.application.booking_use_cases import list_trainer_client_history

    out_lim = max(1, min(10, int(limit)))
    # Pull more rows than out_lim so duplicates can be collapsed without starving the list.
    raw = await list_trainer_client_history(session, trainer_id, client_id, limit=max(40, out_lim * 6))
    seen: set = set()
    out: list[dict[str, Any]] = []
    for it in raw:
        if len(out) >= out_lim:
            break
        sd = it.get("slot_date")
        st_raw = it.get("start_time")
        et_raw = it.get("end_time")
        if sd is None or st_raw is None:
            continue
        if not hasattr(sd, "weekday"):
            continue
        dow = int(sd.weekday())
        st = _coerce_to_time(st_raw)
        if st is None:
            continue
        t_key = _format_time_hhmm(st_raw)
        svc_key = ((it.get("service_name") or "").strip() or "—").lower()
        arena_key = ((it.get("arena_name") or "").strip() or "").lower()
        dedupe_key = (dow, t_key, svc_key, arena_key)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rec = await get_active_recurring_for_booking(session, trainer_id, client_id, dow, st)
        sd_str = sd.isoformat() if hasattr(sd, "isoformat") else str(sd)
        mono = this_week_monday()
        slot_this_iso = mono + timedelta(days=dow)
        apply_first_week_choice = not is_slot_start_in_past_local(slot_this_iso, st)
        out.append(
            {
                "booking_id": int(it["id"]),
                "slot_date": sd_str,
                "start_time": _format_time_hhmm(st_raw),
                "end_time": _format_time_hhmm(et_raw) if et_raw is not None else _format_time_hhmm(st_raw),
                "arena_name": it.get("arena_name"),
                "service_name": (it.get("service_name") or "").strip() or "—",
                "price_tier_label": it.get("price_tier_label"),
                "recurring_slot_id": int(rec["id"]) if rec else None,
                "day_of_week": dow,
                "apply_first_week_choice": apply_first_week_choice,
            }
        )
    return out


async def list_active_recurring_slots_for_trainer_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> list[dict[str, Any]]:
    """Active recurring rules for one trainer–client pair (Mini App card)."""
    r = await session.execute(
        text(
            """
            SELECT id, day_of_week, start_time, end_time
            FROM recurring_client_slots
            WHERE trainer_id = :tid AND client_id = :cid AND status = 'active'
            ORDER BY day_of_week, start_time
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        rid, dow, st, et = int(row[0]), int(row[1]), row[2], row[3]
        dows = RECURRING_WEEKDAY_SHORT_RU[dow] if 0 <= dow <= 6 else "?"
        st_s, et_s = _format_time_hhmm(st), _format_time_hhmm(et)
        out.append(
            {
                "id": rid,
                "day_of_week": dow,
                "start_time": st_s,
                "end_time": et_s,
                "label": f"{dows} {st_s}–{et_s}",
            }
        )
    return out


async def list_upcoming_recurring_bookings_for_trainer_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    *,
    from_date: date,
    limit: int = 16,
) -> list[dict[str, Any]]:
    """
    Next pending/confirmed bookings linked to recurring rules for this client.
    ``from_date``: first calendar day to include (inclusive), typically «today» in NOTIFICATION_TZ.
    """
    lim = max(1, min(50, int(limit)))
    r = await session.execute(
        text(
            """
            SELECT b.id, s.slot_date, s.start_time, b.recurring_client_slot_id, b.status
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.client_id = :cid
              AND b.recurring_client_slot_id IS NOT NULL
              AND b.status IN ('pending', 'confirmed')
              AND s.slot_date >= :from_d
            ORDER BY s.slot_date ASC, s.start_time ASC
            LIMIT :lim
            """
        ),
        {"tid": trainer_id, "cid": client_id, "from_d": from_date, "lim": lim},
    )
    rows: list[dict[str, Any]] = []
    for row in r.fetchall():
        sd = row[1]
        rows.append(
            {
                "booking_id": int(row[0]),
                "slot_date": sd.isoformat() if hasattr(sd, "isoformat") else str(sd),
                "start_time": _format_time_hhmm(row[2]),
                "recurring_slot_id": int(row[3]) if row[3] is not None else None,
                "status": (row[4] or "").strip().lower() or None,
                "kind": "real",
            }
        )
    return rows


async def list_recurring_schedule_preview_for_trainer_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    *,
    from_date: date,
    horizon_weeks: int,
    preview_weeks: int,
) -> list[dict[str, Any]]:
    """
    Hybrid schedule for the client card: real auto-bookings inside the materialization window,
    plus virtual projected dates from active rules (no DB rows) further out / for gaps.

    Sorted ascending by date+time. Virtual rows have ``kind='virtual'`` and ``booking_id=None``.
    """
    h = max(1, min(52, int(horizon_weeks)))
    preview = max(h, min(52, int(preview_weeks)))
    mono = this_week_monday()
    window_end = mono + timedelta(days=7 * h)
    preview_end = mono + timedelta(days=7 * preview)

    real = await list_upcoming_recurring_bookings_for_trainer_client(
        session, trainer_id, client_id, from_date=from_date, limit=50
    )
    real_keys: set[tuple[str, str]] = set()
    for u in real:
        real_keys.add((str(u["slot_date"]), str(u["start_time"])))

    slots = await list_active_recurring_slots_for_trainer_client(session, trainer_id, client_id)
    virtual: list[dict[str, Any]] = []
    for rule in slots:
        rid = int(rule["id"])
        dow = int(rule["day_of_week"])
        st_s = str(rule["start_time"])
        # Walk preview weeks from current Monday
        for i in range(0, preview):
            ws = mono + timedelta(days=7 * i)
            slot_date = ws + timedelta(days=dow)
            if slot_date < from_date:
                continue
            if slot_date >= preview_end:
                break
            key = (slot_date.isoformat(), st_s)
            if key in real_keys:
                continue
            if await _recurring_week_is_skipped(session, rid, ws):
                continue
            st = _parse_hhmm_string(st_s)
            if st is not None and is_slot_start_in_past_local(slot_date, st):
                continue
            # Inside materialization window without a real booking → gap (conflict / not yet filled)
            in_window = slot_date < window_end
            virtual.append(
                {
                    "booking_id": None,
                    "slot_date": slot_date.isoformat(),
                    "start_time": st_s,
                    "recurring_slot_id": rid,
                    "status": None,
                    "kind": "virtual",
                    "in_horizon": in_window,
                    "label_hint": "по правилу" if not in_window else "ожидает автозапись",
                }
            )

    merged = list(real) + virtual
    merged.sort(key=lambda x: (str(x.get("slot_date") or ""), str(x.get("start_time") or "")))
    return merged[: max(8, min(40, preview * max(1, len(slots) or 1)))]


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
    from src.application.trainer_feature_tracking import FEATURE_RECURRING_SET, record_feature_first_use

    await record_feature_first_use(session, trainer_id, FEATURE_RECURRING_SET)
    await session.commit()
    return pk


async def discard_upcoming_bookings_for_recurring_rule(
    session: AsyncSession,
    trainer_id: int,
    recurring_id: int,
) -> int:
    """
    Drop not-yet-started bookings tied to this rule: cancel without client notification and without
    week-skip rows (the rule itself is being removed or replaced).
    """
    from src.application.booking_use_cases import (
        BOOKING_CANCELLATION_SOURCE_RECURRING_DETACH,
        cancel_booking,
    )

    r = await session.execute(
        text(
            """
            SELECT b.id, s.slot_date, s.start_time
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.recurring_client_slot_id = :rid
              AND b.status IN ('pending', 'confirmed')
            ORDER BY s.slot_date, s.start_time
            """
        ),
        {"tid": trainer_id, "rid": recurring_id},
    )
    removed = 0
    for row in r.fetchall():
        bid, sd, st0 = int(row[0]), row[1], row[2]
        if is_slot_start_in_past_local(sd, st0):
            continue
        if await cancel_booking(
            session,
            bid,
            trainer_id,
            notify_client=False,
            record_recurring_week_skip=False,
            cancellation_source=BOOKING_CANCELLATION_SOURCE_RECURRING_DETACH,
        ):
            removed += 1
    return removed


async def cancel_recurring_client_slot(
    session: AsyncSession,
    trainer_id: int,
    recurring_id: int,
) -> tuple[bool, int]:
    """
    Cancel recurring rule and remove forward auto-bookings that have not started yet (silent for client).
    Returns (updated_rule_ok, removed_booking_count).
    """
    r0 = await session.execute(
        text("""
            SELECT 1 FROM recurring_client_slots
            WHERE id = :id AND trainer_id = :tid AND status = 'active'
            LIMIT 1
        """),
        {"id": recurring_id, "tid": trainer_id},
    )
    if r0.fetchone() is None:
        return False, 0
    removed = await discard_upcoming_bookings_for_recurring_rule(session, trainer_id, recurring_id)
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
        await session.commit()
        return False, removed
    await session.commit()
    return True, removed


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

    Skips sandbox clients, past slots, materialization week skips, and when this client already has a
    non-cancelled booking on the same date+start (duplicate).

    Slot selection: reuse an ``available`` row at exact start time if present; otherwise create an
    individual interval (off-grid allowed). Occupancy: ``ensure_individual_slot_for_quick_book`` rejects
    overlap with any existing slot that already has active bookings (including other clients) or group slots.
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
        # No template row: create an individual interval (same idea as «repeat exact time» / quick book).
        et_raw = rec["end_time"]
        et = et_raw.replace(second=0, microsecond=0) if hasattr(et_raw, "replace") else et_raw
        duration_minutes = _booking_interval_duration_minutes(st, et)
        start_minutes = int(st.hour) * 60 + int(st.minute)
        try:
            slot_id = await ensure_individual_slot_for_quick_book(
                session,
                trainer_id,
                slot_date,
                start_minutes,
                duration_minutes,
                allow_off_grid_interval=True,
                arena_id=None,
            )
        except ValueError:
            # Overlap, group slot, or invalid interval — cannot auto-place.
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
    min_week_index: int = 0,
) -> int:
    """
    Fill missing auto-bookings **inside** a rolling window of ``horizon_weeks`` from this Monday.

    For each active rule, walks only weeks ``[min_week_index, min_week_index + horizon)`` —
    does **not** keep creating further out when near weeks already have bookings (that was the
    bug that piled up ~year of futures).

    Does **not** call ``generate_slots_for_week``. Returns count of newly created bookings.
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
    start_i = max(0, int(min_week_index))
    created = 0
    for rec in recs:
        for i in range(start_i, start_i + h):
            ws = mono + timedelta(days=7 * i)
            if await materialize_recurring_rule_for_week(session, trainer_id, rec, ws, service_id):
                created += 1
    return created


async def prune_recurring_bookings_beyond_horizon(
    session: AsyncSession,
    trainer_id: int,
    *,
    horizon_weeks: int,
    recurring_ids: list[int] | None = None,
) -> int:
    """
    Silently cancel future auto-bookings linked to active rules that fall **outside** the
    rolling horizon window (slot_date >= this_monday + horizon_weeks).

    Past sessions and weeks inside the window are kept. No week-skip rows (these were
    over-materialized, not trainer «skip this week»).
    """
    from src.application.booking_use_cases import (
        BOOKING_CANCELLATION_SOURCE_RECURRING_DETACH,
        cancel_booking,
    )

    h = max(1, min(52, int(horizon_weeks)))
    cutoff = this_week_monday() + timedelta(days=7 * h)
    wanted: set[int] | None = None
    if recurring_ids is not None:
        wanted = {int(x) for x in recurring_ids}
        if not wanted:
            return 0

    r = await session.execute(
        text(
            """
            SELECT b.id, s.slot_date, s.start_time, b.recurring_client_slot_id
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN recurring_client_slots r ON r.id = b.recurring_client_slot_id
            WHERE b.trainer_id = :tid
              AND r.trainer_id = :tid
              AND r.status = 'active'
              AND b.status IN ('pending', 'confirmed')
              AND s.slot_date >= :cutoff
            ORDER BY s.slot_date, s.start_time
            """
        ),
        {"tid": trainer_id, "cutoff": cutoff},
    )
    removed = 0
    for row in r.fetchall():
        bid, sd, st0, rid = int(row[0]), row[1], row[2], int(row[3])
        if wanted is not None and rid not in wanted:
            continue
        if is_slot_start_in_past_local(sd, st0):
            continue
        if await cancel_booking(
            session,
            bid,
            trainer_id,
            notify_client=False,
            record_recurring_week_skip=False,
            cancellation_source=BOOKING_CANCELLATION_SOURCE_RECURRING_DETACH,
        ):
            removed += 1
    return removed


async def maintain_recurring_horizon(
    session: AsyncSession,
    trainer_id: int,
    *,
    horizon_weeks: int,
    recurring_ids: list[int] | None = None,
    min_week_index: int = 0,
) -> dict[str, int]:
    """Prune over-materialized futures, then fill gaps inside the window."""
    pruned = await prune_recurring_bookings_beyond_horizon(
        session,
        trainer_id,
        horizon_weeks=horizon_weeks,
        recurring_ids=recurring_ids,
    )
    created = await materialize_recurring_horizon(
        session,
        trainer_id,
        horizon_weeks=horizon_weeks,
        recurring_ids=recurring_ids,
        min_week_index=min_week_index,
    )
    return {"pruned": pruned, "created": created}


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
