"""
Stats for trainers (subscription value) and platform (admin).
Read-only aggregates; no side effects.
"""
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_schedule_use_cases import this_week_monday


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    if d.month == 12:
        return d.replace(day=31)
    return (d.replace(month=d.month + 1, day=1)) - timedelta(days=1)


async def get_trainer_stats(session: AsyncSession, trainer_id: int) -> dict:
    """
    Aggregates for trainer dashboard: week/month bookings, load, new clients, rating.
    Periods: this week (Mon–Sun), this month, last 30 days for new clients.
    """
    today = date.today()
    week_start = this_week_monday()
    week_end = week_start + timedelta(days=6)
    month_start = _month_start(today)
    month_end = _month_end(today)

    # Bookings this week (non-cancelled): count and split into completed vs upcoming
    r = await session.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE (s.slot_date + s.end_time) < CURRENT_TIMESTAMP OR b.status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE (s.slot_date + s.end_time) >= CURRENT_TIMESTAMP AND b.status != 'cancelled') AS upcoming
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.slot_date >= :ws AND s.slot_date <= :we
        """),
        {"tid": trainer_id, "ws": week_start, "we": week_end},
    )
    row = r.fetchone()
    week_completed = row[0] or 0
    week_upcoming = row[1] or 0
    week_total = week_completed + week_upcoming

    # Bookings this month
    r = await session.execute(
        text("""
            SELECT COUNT(*)
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.slot_date >= :ms AND s.slot_date <= :me
        """),
        {"tid": trainer_id, "ms": month_start, "me": month_end},
    )
    month_total = (r.fetchone() or (0,))[0]

    # Load this week: slots total vs booked (only slots in week range)
    r = await session.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'booked') AS booked
            FROM slots
            WHERE trainer_id = :tid AND slot_date >= :ws AND slot_date <= :we
              AND status IN ('available', 'booked')
        """),
        {"tid": trainer_id, "ws": week_start, "we": week_end},
    )
    row = r.fetchone()
    week_slots_total = row[0] or 0
    week_slots_booked = row[1] or 0
    load_pct = round(100 * week_slots_booked / week_slots_total, 0) if week_slots_total else None

    # New clients in last 30 days: first booking with this trainer in the period
    r = await session.execute(
        text("""
            SELECT COUNT(DISTINCT b.client_id)
            FROM bookings b
            WHERE b.trainer_id = :tid
              AND b.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
              AND NOT EXISTS (
                  SELECT 1 FROM bookings b2
                  WHERE b2.trainer_id = b.trainer_id AND b2.client_id = b.client_id
                    AND b2.created_at < CURRENT_TIMESTAMP - INTERVAL '30 days'
              )
        """),
        {"tid": trainer_id},
    )
    new_clients_30d = (r.fetchone() or (0,))[0]

    # Rating from profile
    r = await session.execute(
        text("SELECT rating_avg, rating_count FROM trainer_profiles WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    rating_avg = float(row[0]) if row and row[0] is not None else None
    rating_count = (row[1] or 0) if row else 0

    return {
        "week_total": week_total,
        "week_completed": week_completed,
        "week_upcoming": week_upcoming,
        "month_total": month_total,
        "week_slots_total": week_slots_total,
        "week_slots_booked": week_slots_booked,
        "load_pct": load_pct,
        "new_clients_30d": new_clients_30d,
        "rating_avg": rating_avg,
        "rating_count": rating_count,
        "week_start": week_start,
        "week_end": week_end,
        "month_start": month_start,
        "month_end": month_end,
    }


async def get_platform_stats(session: AsyncSession) -> dict:
    """
    Full platform stats for admin: current state, 7d/30d periods, trainers breakdown,
    conversion and signals for business decisions.
    """
    today = date.today()
    week_start = this_week_monday()
    week_end = week_start + timedelta(days=6)

    # --- Trainers: by status + totals ---
    r = await session.execute(
        text("""
            SELECT status, COUNT(*) FROM trainers GROUP BY status ORDER BY status
        """),
    )
    trainers_by_status = {row[0]: row[1] for row in r.fetchall()}
    trainers_total = sum(trainers_by_status.values())
    trainers_pending_moderation = trainers_by_status.get("pending_profile", 0)
    trainers_active = trainers_by_status.get("active", 0)
    trainers_with_telegram = 0  # active and linked
    if trainers_active:
        r = await session.execute(
            text("SELECT COUNT(*) FROM trainers WHERE status = 'active' AND telegram_id IS NOT NULL"),
        )
        trainers_with_telegram = (r.fetchone() or (0,))[0]

    # --- Current state: today & this week ---
    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.status != 'cancelled' AND s.slot_date = :d
        """),
        {"d": today},
    )
    bookings_today = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.status != 'cancelled'
              AND s.slot_date >= :ws AND s.slot_date <= :we
              AND (s.slot_date + s.end_time) >= CURRENT_TIMESTAMP
        """),
        {"ws": week_start, "we": week_end},
    )
    bookings_upcoming_week = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("SELECT COUNT(*) FROM client_requests WHERE status = 'new'"),
    )
    requests_open_now = (r.fetchone() or (0,))[0]

    # --- Last 7 days ---
    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM bookings
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    bookings_7d = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM client_requests
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    requests_7d = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM trainers
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    trainers_created_7d = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM client_request_responses
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    responses_7d = (r.fetchone() or (0,))[0]

    # --- Last 30 days ---
    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM bookings
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    bookings_30d = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'new') AS new_count
            FROM client_requests
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    row = r.fetchone()
    requests_30d = row[0] or 0
    requests_new_30d = row[1] or 0

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM trainers
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    trainers_created_30d = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM client_request_responses
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    responses_30d = (r.fetchone() or (0,))[0]

    # --- Conversion: requests that got at least one response (30d) ---
    r = await session.execute(
        text("""
            SELECT COUNT(DISTINCT r.id)
            FROM client_requests r
            INNER JOIN client_request_responses resp ON resp.client_request_id = r.id
            WHERE r.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    requests_with_response_30d = (r.fetchone() or (0,))[0]
    conversion_pct = round(100 * requests_with_response_30d / requests_30d, 0) if requests_30d else None

    # --- Requests still open (created 7+ days ago) — signal "stale" ---
    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM client_requests
            WHERE status = 'new' AND created_at < CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    requests_stale = (r.fetchone() or (0,))[0]

    return {
        "trainers_by_status": trainers_by_status,
        "trainers_total": trainers_total,
        "trainers_pending_moderation": trainers_pending_moderation,
        "trainers_active": trainers_active,
        "trainers_with_telegram": trainers_with_telegram,
        "bookings_today": bookings_today,
        "bookings_upcoming_week": bookings_upcoming_week,
        "requests_open_now": requests_open_now,
        "bookings_7d": bookings_7d,
        "requests_7d": requests_7d,
        "trainers_created_7d": trainers_created_7d,
        "responses_7d": responses_7d,
        "bookings_30d": bookings_30d,
        "requests_30d": requests_30d,
        "requests_new_30d": requests_new_30d,
        "trainers_created_30d": trainers_created_30d,
        "responses_30d": responses_30d,
        "requests_with_response_30d": requests_with_response_30d,
        "conversion_pct": conversion_pct,
        "requests_stale": requests_stale,
        "today": today,
        "week_start": week_start,
        "week_end": week_end,
    }
