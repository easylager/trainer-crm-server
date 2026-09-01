"""
Aggregates completed training stats for client Mini App motivation screens.

Uses the same slot timestamp projection as reminders and client bookings (Europe/Minsk).
Only counts ``status = 'completed'`` bookings and excludes sandbox demo rows (``NOT is_sandbox``).

Calendar week streak (``streak_weeks``):
- Week = ISO Monday–Sunday in **Europe/Minsk** wall calendar (derived from slot start:
  ``datetime.combine(slot_date, start_time, tzinfo=Europe/Minsk)``).
- A week "counts" if there is at least one completed non-sandbox booking whose slot start
  falls in that week.
- Streak length = consecutive counted weeks ending at ``end_week``, where ``end_week`` is the
  Monday of the latest counted week **not after** this week's Monday (today in Minsk).
  Equivalently: ``end_week = max({ w in W | w <= today_monday })`` for week set ``W``;
  then walk backwards by 7 days while still in ``W``.
  This avoids inflating the streak for a current week that has no completed session yet
  (that week is not in ``W``, so ``end_week`` moves to the previous Monday that had work).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.notification_hours import NOTIFICATION_TZ

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

_MILESTONE_TARGETS = (5, 10, 25, 50, 100, 250, 500)
_TZ = ZoneInfo(NOTIFICATION_TZ)


def _slot_start_ts_expr(alias: str = "s") -> str:
    return f"(({alias}.slot_date + {alias}.start_time) AT TIME ZONE '{NOTIFICATION_TZ}')"


def _slot_end_ts_expr(alias: str = "s") -> str:
    return f"(({alias}.slot_date + {alias}.end_time) AT TIME ZONE '{NOTIFICATION_TZ}')"


def _minsk_week_monday(d: date) -> date:
    """Monday (inclusive) of the ISO calendar week containing ``d`` (Monday = 0)."""
    return d - timedelta(days=d.weekday())


def compute_calendar_week_streak_completed(
    slot_rows: list[tuple[date, time | None]],
    *,
    reference_now: datetime,
) -> int:
    """
    Consecutive calendar weeks (Minsk) with ≥1 completed session, ending at the latest
    such week not after the current week's Monday (conservative for an empty current week).
    """
    if not slot_rows:
        return 0
    if reference_now.tzinfo is None:
        ref = reference_now.replace(tzinfo=timezone.utc).astimezone(_TZ)
    else:
        ref = reference_now.astimezone(_TZ)
    today_monday = _minsk_week_monday(ref.date())
    week_mondays: set[date] = set()
    for slot_date, start_time in slot_rows:
        if slot_date is None:
            continue
        st = start_time if isinstance(start_time, time) else time(0, 0)
        dt_local = datetime.combine(slot_date, st, tzinfo=_TZ)
        week_mondays.add(_minsk_week_monday(dt_local.date()))
    if not week_mondays:
        return 0
    eligible = [w for w in week_mondays if w <= today_monday]
    if not eligible:
        return 0
    end_week = max(eligible)
    streak = 0
    w = end_week
    while w in week_mondays:
        streak += 1
        w = w - timedelta(days=7)
    return streak


def _empty_snapshot() -> dict[str, Any]:
    """Shape returned when the Telegram user has no CRM client row."""
    return {
        "completed_total": 0,
        "completed_minutes_total": 0,
        "completed_last_30d": 0,
        "completed_prev_30d": 0,
        "distinct_trainers_completed": 0,
        "upcoming_bookings_count": 0,
        "last_completed_at": None,
        "days_since_last_completed": None,
        "first_completed_at": None,
        "streak_weeks": 0,
        "top_trainer": None,
        "next_milestone": None,
    }


def _next_milestone(completed_total: int) -> dict[str, int] | None:
    for target in _MILESTONE_TARGETS:
        if completed_total < target:
            return {"target": target, "remaining": target - completed_total}
    return None


async def get_client_activity_snapshot(
    session: AsyncSession,
    *,
    client_id: int | None,
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    """
    Return motivational stats backed by immutable completed sessions + upcoming count.

    ``completed_*`` windows use rolling 30-day periods from ``CURRENT_TIMESTAMP`` (DB),
    keyed by scheduled slot start in Minsk timezone.

    ``reference_now`` (tests only): Minsk-aware instant for streak and client-relative copy;
    defaults to wall-clock now in Europe/Minsk.
    """
    if client_id is None:
        return _empty_snapshot()

    clock = reference_now if reference_now is not None else datetime.now(_TZ)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=_TZ)

    st = _slot_start_ts_expr("s")
    en = _slot_end_ts_expr("s")
    dur = "(GREATEST(0, (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60.0))::bigint)"

    r = await session.execute(
        text(
            f"""
            SELECT
                COUNT(*)::int AS completed_total,
                COALESCE(SUM({dur}), 0)::bigint AS completed_minutes_total,
                COUNT(*) FILTER (
                    WHERE {st} >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                )::int AS completed_last_30d,
                COUNT(*) FILTER (
                    WHERE {st} >= CURRENT_TIMESTAMP - INTERVAL '60 days'
                      AND {st} < CURRENT_TIMESTAMP - INTERVAL '30 days'
                )::int AS completed_prev_30d,
                COUNT(DISTINCT b.trainer_id)::int AS distinct_trainers_completed,
                MAX({st}) AS last_completed_at,
                MIN({st}) AS first_completed_at,
                CASE
                    WHEN MAX({st}) IS NULL THEN NULL
                    ELSE FLOOR(
                        EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MAX({st}))) / 86400.0
                    )::int
                END AS days_since_last_completed
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.client_id = :cid
              AND b.status = 'completed'
              AND NOT b.is_sandbox
            """
        ),
        {"cid": client_id},
    )
    row = r.fetchone()
    if row is None:
        snap = _empty_snapshot()
        snap["upcoming_bookings_count"] = await _count_upcoming_client_bookings(session, client_id)
        return snap

    completed_total = int(row[0] or 0)
    minutes_total = int(row[1] or 0)
    completed_last_30d = int(row[2] or 0)
    completed_prev_30d = int(row[3] or 0)
    distinct_trainers = int(row[4] or 0)
    last_done = row[5]
    first_done = row[6]
    days_since = row[7]

    last_iso: str | None
    if last_done is None:
        last_iso = None
    elif isinstance(last_done, datetime):
        last_iso = last_done.isoformat()
    else:
        last_iso = str(last_done)

    first_iso: str | None
    if first_done is None:
        first_iso = None
    elif isinstance(first_done, datetime):
        first_iso = first_done.isoformat()
    else:
        first_iso = str(first_done)

    r_slots = await session.execute(
        text(
            """
            SELECT s.slot_date, s.start_time
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.client_id = :cid
              AND b.status = 'completed'
              AND NOT b.is_sandbox
            """
        ),
        {"cid": client_id},
    )
    slot_rows = [(row[0], row[1]) for row in r_slots.fetchall()]
    streak_weeks = compute_calendar_week_streak_completed(slot_rows, reference_now=clock)

    top_trainer = await _fetch_top_trainer_completed(session, client_id)

    upcoming = await _count_upcoming_client_bookings(session, client_id)

    return {
        "completed_total": completed_total,
        "completed_minutes_total": minutes_total,
        "completed_last_30d": completed_last_30d,
        "completed_prev_30d": completed_prev_30d,
        "distinct_trainers_completed": distinct_trainers,
        "upcoming_bookings_count": upcoming,
        "last_completed_at": last_iso,
        "days_since_last_completed": int(days_since) if days_since is not None else None,
        "first_completed_at": first_iso,
        "streak_weeks": streak_weeks,
        "top_trainer": top_trainer,
        "next_milestone": _next_milestone(completed_total),
    }


async def _fetch_top_trainer_completed(
    session: AsyncSession,
    client_id: int,
) -> dict[str, Any] | None:
    """Trainer with most completed (non-sandbox) sessions for this client."""
    r = await session.execute(
        text(
            """
            SELECT
                b.trainer_id,
                COALESCE(NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''), 'Тренер') AS display_name,
                COUNT(*)::int AS cnt
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            WHERE b.client_id = :cid
              AND b.status = 'completed'
              AND NOT b.is_sandbox
            GROUP BY b.trainer_id, p.first_name, p.last_name
            ORDER BY cnt DESC, b.trainer_id ASC
            LIMIT 1
            """
        ),
        {"cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return None
    tid, name, cnt = int(row[0]), (row[1] or "Тренер").strip() or "Тренер", int(row[2] or 0)
    if cnt < 1:
        return None
    return {
        "trainer_id": tid,
        "name": name,
        "completed_sessions": cnt,
    }


async def _count_upcoming_client_bookings(session: AsyncSession, client_id: int) -> int:
    """Same temporal rule as ``list_bookings_for_client``: future slot end in Minsk TZ."""
    en = _slot_end_ts_expr("s")
    r = await session.execute(
        text(
            f"""
            SELECT COUNT(*)::int
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.client_id = :cid
              AND s.status IN ('available', 'booked')
              AND b.status IN ('pending', 'confirmed')
              AND {en} > CURRENT_TIMESTAMP
            """
        ),
        {"cid": client_id},
    )
    return int((r.fetchone() or (0,))[0] or 0)
