"""
Trainer daily/weekly digest aggregators — pure read functions for the morning/weekly ritual push.

Two aggregators and one scheduler helper:

- ``get_trainer_daily_digest(session, trainer_id, today)`` → today's run-sheet (sessions, gaps ≥ 2h,
  first-timers, pending confirmations, open catalog requests). Excludes cancelled/declined/no_show.
  Empty list = trainer has 0 sessions today → loop suppresses the push. Includes ``catalog_pulse`` for
  yesterday (Minsk): favorite saves + Telegram clicks in that calendar day, plus lifetime profile-view
  count for digest copy when the window had no saves/clicks.

- ``get_trainer_weekly_digest(session, trainer_id, today)`` → Sunday preview. Past = Mon..Sat just
  finished (factual money from pass_redemptions / certificate_booking_credits), upcoming = next
  Mon..Sun. Drought ladder triggers after 3+ consecutive zero-booking days. ``catalog_pulse`` uses
  the same Mon..Sat local window + lifetime profile views for fallback.

- ``resolve_digest_send_time(...)`` → Europe/Minsk wall-clock time for the **daily** digest.
  Priority: explicit ``trainers.digest_send_time`` → иначе утренний слот по умолчанию (08:00) или
  раньше, если первая тренировка требует (``min(08:00, first_session - lead)``), без отправки
  днём «как за час до вечерней тренировки». Clamped to push window.
- Weekly Sunday digest: ``resolve_weekly_digest_send_time`` — вечерний слот по умолчанию (не зависит
  от ``digest_send_time``, чтобы не совпадать с утренним обзором).

Drought ladder order (first match wins; case 7 = silence):
  1. Open catalog requests > 0
  2. Catalog hidden (``is_catalog_visible = false``)
  3. No available slots in next 14 days
  4. Dormant clients (≥ 1 completed > 21 days ago, no future bookings)
  5. Profile incomplete (``full_profile_complete = false``)
  6. No weekly schedule template
  7. Silence (no honest nudge to offer)
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.demand_signals_use_cases import get_signals_lifetime_totals
from src.infrastructure.db.models import (
    DEMAND_EVENT_CATALOG_FAVORITE,
    DEMAND_EVENT_CONTACT_CLICK,
)
from src.infrastructure.repositories.demand_signals_repository import DemandSignalsRepository
from src.shared.notification_hours import (
    NOTIFICATION_START_HOUR,
    NOTIFICATION_TZ,
)

# Minimum gap between consecutive sessions to surface in digest ("между HH:MM и HH:MM").
GAP_MIN_MINUTES = 120

# Consecutive zero-booking days (counted backward from yesterday) needed to trigger drought block.
DROUGHT_CONSECUTIVE_DAYS = 3

# How far back we look for "dormant" clients in drought ladder case 4.
DORMANT_CLIENT_MIN_DAYS = 21
DORMANT_CLIENT_SAMPLE_LIMIT = 3

# Horizon for "no available slots" check in drought ladder case 3.
DROUGHT_SLOT_HORIZON_DAYS = 14

# Авто-режим (digest_send_time IS NULL): слот утром, не «за час» до вечерней тренировки.
MORNING_DIGEST_AUTO_DEFAULT_T = time(8, 0)
# Sunday ledger + forward-plan digest — deliberately not tied to morning digest settings.
WEEKLY_DIGEST_DEFAULT_SEND_T = time(20, 0)


async def _digest_catalog_pulse_for_local_range(
    session: AsyncSession,
    trainer_id: int,
    *,
    range_start: date,
    range_end: date,
) -> dict[str, int]:
    """
    Catalog «pulse» for digest copy: favorite saves + Telegram contact clicks in
    [range_start 00:00, range_end+1 00:00) Europe/Minsk, plus lifetime profile_view count
    for positive fallback when the window had no saves/clicks.
    """
    tz = ZoneInfo(NOTIFICATION_TZ)
    since = datetime.combine(range_start, time.min, tzinfo=tz)
    until = datetime.combine(range_end + timedelta(days=1), time.min, tzinfo=tz)
    repo = DemandSignalsRepository(session)
    counts = await repo.aggregate_window(
        trainer_id=trainer_id,
        kinds=(DEMAND_EVENT_CATALOG_FAVORITE, DEMAND_EVENT_CONTACT_CLICK),
        since=since,
        until=until,
    )
    totals = await get_signals_lifetime_totals(session, trainer_id=trainer_id)
    return {
        "favorites": int(counts.get(DEMAND_EVENT_CATALOG_FAVORITE, 0)),
        "contact_clicks": int(counts.get(DEMAND_EVENT_CONTACT_CLICK, 0)),
        "profile_views_total": int(totals["profile_views"]),
    }


# =============================================================================
# Daily digest
# =============================================================================


async def get_trainer_daily_digest(
    session: AsyncSession,
    trainer_id: int,
    today: date,
) -> dict[str, Any]:
    """
    Aggregated picture of today for one trainer.

    Returns dict with:
        ``sessions``: list of session dicts ordered by start_time (see shape below).
        ``sessions_count``: len(sessions).
        ``first_session_start``: ``time`` of earliest session, or None.
        ``gaps``: list of gaps ≥ GAP_MIN_MINUTES between consecutive sessions.
        ``first_timers_count``: how many sessions are first-ever with this trainer.
        ``pending_confirmations_count``: sessions with status='pending' (trainer hasn't accepted).
        ``pending_requests_count``: open catalog requests awaiting trainer reply.

    Session shape:
        ``{"booking_id", "start_time", "end_time", "client_name", "client_id",
           "arena_name", "service_name", "is_first_time", "status"}``
    """
    r = await session.execute(
        text(
            """
            SELECT b.id AS booking_id,
                   s.start_time,
                   s.end_time,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   c.id AS client_id,
                   a.name AS arena_name,
                   svc.name AS service_name,
                   b.status,
                   (
                       SELECT COUNT(*) FROM bookings b2
                       JOIN slots s2 ON s2.id = b2.slot_id
                       WHERE b2.trainer_id = :tid
                         AND b2.client_id = c.id
                         AND b2.id <> b.id
                         AND b2.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                         AND (s2.slot_date < :today
                              OR (s2.slot_date = :today AND s2.start_time < s.start_time))
                   )::int AS prior_sessions_count
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            JOIN services svc ON svc.id = b.service_id
            LEFT JOIN arenas a ON a.id = COALESCE(b.arena_id, s.arena_id)
            WHERE b.trainer_id = :tid
              AND s.slot_date = :today
              AND b.status IN ('pending', 'confirmed')
            ORDER BY s.start_time ASC
            """
        ),
        {"tid": trainer_id, "today": today},
    )
    rows = r.fetchall()

    sessions: list[dict[str, Any]] = []
    for row in rows:
        (
            booking_id,
            start_t,
            end_t,
            client_name,
            client_id,
            arena_name,
            service_name,
            status,
            prior_count,
        ) = row
        sessions.append(
            {
                "booking_id": int(booking_id),
                "start_time": start_t,
                "end_time": end_t,
                "client_name": (client_name or "").strip() or "Клиент",
                "client_id": int(client_id) if client_id is not None else None,
                "arena_name": arena_name,
                "service_name": service_name,
                "is_first_time": int(prior_count or 0) == 0,
                "status": status,
            }
        )

    gaps = _compute_gaps(sessions, min_minutes=GAP_MIN_MINUTES)

    pending_requests_count = await _count_open_catalog_requests(session, trainer_id)
    pending_confirmations_count = sum(1 for s in sessions if s["status"] == "pending")
    first_timers_count = sum(1 for s in sessions if s["is_first_time"])

    yesterday = today - timedelta(days=1)
    catalog_pulse = await _digest_catalog_pulse_for_local_range(
        session, trainer_id, range_start=yesterday, range_end=yesterday
    )

    return {
        "date": today,
        "trainer_id": trainer_id,
        "timezone": NOTIFICATION_TZ,
        "sessions": sessions,
        "sessions_count": len(sessions),
        "first_session_start": sessions[0]["start_time"] if sessions else None,
        "gaps": gaps,
        "first_timers_count": first_timers_count,
        "pending_confirmations_count": pending_confirmations_count,
        "pending_requests_count": pending_requests_count,
        "catalog_pulse": catalog_pulse,
    }


def _compute_gaps(
    sessions: list[dict[str, Any]], *, min_minutes: int
) -> list[dict[str, Any]]:
    """Gaps ≥ min_minutes between consecutive sessions (sorted by start_time)."""
    if len(sessions) < 2:
        return []
    out: list[dict[str, Any]] = []
    for i in range(1, len(sessions)):
        prev_end: time = sessions[i - 1]["end_time"]
        curr_start: time = sessions[i]["start_time"]
        gap_minutes = (curr_start.hour * 60 + curr_start.minute) - (
            prev_end.hour * 60 + prev_end.minute
        )
        if gap_minutes >= min_minutes:
            out.append(
                {
                    "from_time": prev_end,
                    "to_time": curr_start,
                    "duration_minutes": gap_minutes,
                }
            )
    return out


async def _count_open_catalog_requests(
    session: AsyncSession, trainer_id: int
) -> int:
    """
    Open ``client_requests`` (status='new') matching trainer's profile city + one of trainer's services,
    not yet responded or declined by this trainer. This is the same city+service+NOT-EXISTS shape the
    legacy ``run_daily_request_reminder_loop`` used; its reminder role migrated here (morning digest).
    """
    r = await session.execute(
        text(
            """
            SELECT COUNT(DISTINCT req.id)::int
            FROM client_requests req
            INNER JOIN trainer_profiles p ON p.trainer_id = :tid AND p.city_id = req.city_id
            INNER JOIN trainer_services ts
                ON ts.trainer_id = :tid AND ts.service_id = req.service_id
            WHERE req.status = 'new'
              AND (req.trainer_id IS NULL OR req.trainer_id = :tid)
              AND NOT EXISTS (
                  SELECT 1 FROM client_request_responses resp
                  WHERE resp.client_request_id = req.id AND resp.trainer_id = :tid
              )
              AND NOT EXISTS (
                  SELECT 1 FROM client_request_declines d
                  WHERE d.client_request_id = req.id AND d.trainer_id = :tid
              )
            """
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


# =============================================================================
# Weekly digest (Sunday)
# =============================================================================


async def get_trainer_weekly_digest(
    session: AsyncSession,
    trainer_id: int,
    today: date,
) -> dict[str, Any]:
    """
    Sunday preview:
      - Past week (Mon..Sat that just finished): factual earnings.
      - Upcoming week (Mon..Sun starting tomorrow): sessions, new clients, empty days, heaviest day.
      - Drought block (only if ≥ DROUGHT_CONSECUTIVE_DAYS of consecutive zero-booking days just ended).
    """
    past_start = today - timedelta(days=6)
    past_end = today - timedelta(days=1)
    up_start = today + timedelta(days=1)
    up_end = today + timedelta(days=7)

    past = await _weekly_past_earnings(session, trainer_id, past_start, past_end)
    upcoming = await _weekly_upcoming_overview(session, trainer_id, up_start, up_end)
    drought = await _weekly_drought_block(session, trainer_id, today)
    catalog_pulse = await _digest_catalog_pulse_for_local_range(
        session, trainer_id, range_start=past_start, range_end=past_end
    )

    return {
        "trainer_id": trainer_id,
        "timezone": NOTIFICATION_TZ,
        "today": today,
        "past_week": past,
        "upcoming_week": upcoming,
        "drought": drought,
        "catalog_pulse": catalog_pulse,
    }


async def _weekly_past_earnings(
    session: AsyncSession, trainer_id: int, start: date, end: date
) -> dict[str, Any]:
    """
    Factual earnings Mon..Sat just finished. Based on actually-applied rows:
    - Cash = COALESCE(booking_price_cents, 0) for completed bookings with NO pass_redemption AND NO cert credit.
    - Pass sessions = count of pass_redemptions for those bookings.
    - Cert cents = sum of certificate_booking_credits.amount_cents for those bookings.
    """
    r = await session.execute(
        text(
            """
            WITH done AS (
                SELECT b.id, b.booking_price_cents
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status = 'completed'
                  AND s.slot_date BETWEEN :d_from AND :d_to
            )
            SELECT
                COUNT(*)::int AS completed_count,
                COALESCE(SUM(
                    CASE
                        WHEN pr.booking_id IS NULL AND cbc.booking_id IS NULL
                             THEN COALESCE(done.booking_price_cents, 0)
                        ELSE 0
                    END
                ), 0)::bigint AS cash_cents,
                COUNT(pr.booking_id)::int AS pass_sessions_count,
                COALESCE(SUM(cbc.amount_cents), 0)::bigint AS cert_cents
            FROM done
            LEFT JOIN pass_redemptions pr ON pr.booking_id = done.id
            LEFT JOIN certificate_booking_credits cbc ON cbc.booking_id = done.id
            """
        ),
        {"tid": trainer_id, "d_from": start, "d_to": end},
    )
    row = r.fetchone()
    if not row:
        return {
            "start_date": start,
            "end_date": end,
            "completed_count": 0,
            "cash_cents": 0,
            "pass_sessions_count": 0,
            "cert_cents": 0,
        }
    return {
        "start_date": start,
        "end_date": end,
        "completed_count": int(row[0] or 0),
        "cash_cents": int(row[1] or 0),
        "pass_sessions_count": int(row[2] or 0),
        "cert_cents": int(row[3] or 0),
    }


async def _weekly_upcoming_overview(
    session: AsyncSession, trainer_id: int, start: date, end: date
) -> dict[str, Any]:
    """
    Next week: total sessions, per-day counts, empty days, heaviest day, new-client names
    (first-ever booking with this trainer starts during the upcoming week).
    """
    r_day = await session.execute(
        text(
            """
            SELECT s.slot_date, COUNT(*)::int
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
              AND s.slot_date BETWEEN :d_from AND :d_to
            GROUP BY s.slot_date
            """
        ),
        {"tid": trainer_id, "d_from": start, "d_to": end},
    )
    per_day: dict[date, int] = {row[0]: int(row[1]) for row in r_day.fetchall()}
    total = sum(per_day.values())

    empty_days: list[date] = []
    cur = start
    while cur <= end:
        if per_day.get(cur, 0) == 0:
            empty_days.append(cur)
        cur += timedelta(days=1)

    heaviest: Optional[dict[str, Any]] = None
    if per_day:
        h_date, h_count = max(per_day.items(), key=lambda kv: kv[1])
        if h_count > 0:
            heaviest = {"date": h_date, "count": h_count}

    r_new = await session.execute(
        text(
            """
            SELECT c.id,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   MIN(s.slot_date) AS first_slot
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            WHERE b.trainer_id = :tid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
              AND s.slot_date BETWEEN :d_from AND :d_to
              AND NOT EXISTS (
                  SELECT 1 FROM bookings b_prev
                  JOIN slots s_prev ON s_prev.id = b_prev.slot_id
                  WHERE b_prev.trainer_id = :tid
                    AND b_prev.client_id = c.id
                    AND b_prev.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                    AND s_prev.slot_date < :d_from
              )
            GROUP BY c.id, client_name
            ORDER BY first_slot ASC, c.id ASC
            """
        ),
        {"tid": trainer_id, "d_from": start, "d_to": end},
    )
    new_clients: list[dict[str, Any]] = [
        {
            "client_id": int(row[0]),
            "client_name": (row[1] or "").strip() or "Клиент",
            "first_slot_date": row[2],
        }
        for row in r_new.fetchall()
    ]

    return {
        "start_date": start,
        "end_date": end,
        "sessions_count": total,
        "per_day_counts": per_day,
        "empty_days": empty_days,
        "heaviest_day": heaviest,
        "new_clients": new_clients,
    }


async def _weekly_drought_block(
    session: AsyncSession, trainer_id: int, today: date
) -> dict[str, Any]:
    """
    Drought block: appears only when ≥ DROUGHT_CONSECUTIVE_DAYS of zero-booking days
    ended yesterday. Ladder: first matching case wins; case 7 = silence.
    """
    skip_days = await _consecutive_skip_days_before(session, trainer_id, today)

    if skip_days < DROUGHT_CONSECUTIVE_DAYS:
        return {"triggered": False, "consecutive_skip_days": skip_days, "case": None}

    req_count = await _count_open_catalog_requests(session, trainer_id)
    if req_count > 0:
        return {
            "triggered": True,
            "consecutive_skip_days": skip_days,
            "case": 1,
            "case_key": "open_requests",
            "data": {"open_requests_count": req_count},
        }

    r_t = await session.execute(
        text("SELECT is_catalog_visible FROM trainers WHERE id = :tid"),
        {"tid": trainer_id},
    )
    t_row = r_t.fetchone()
    is_catalog_visible = bool(t_row[0]) if t_row else True

    if not is_catalog_visible:
        return {
            "triggered": True,
            "consecutive_skip_days": skip_days,
            "case": 2,
            "case_key": "catalog_hidden",
            "data": {},
        }

    r_avail = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM slots
            WHERE trainer_id = :tid
              AND slot_date BETWEEN :d_from AND :d_to
              AND status = 'available'
            """
        ),
        {
            "tid": trainer_id,
            "d_from": today,
            "d_to": today + timedelta(days=DROUGHT_SLOT_HORIZON_DAYS),
        },
    )
    avail_row = r_avail.fetchone()
    avail_count = int(avail_row[0]) if avail_row else 0
    if avail_count == 0:
        return {
            "triggered": True,
            "consecutive_skip_days": skip_days,
            "case": 3,
            "case_key": "no_available_slots",
            "data": {"horizon_days": DROUGHT_SLOT_HORIZON_DAYS},
        }

    dormant = await _dormant_clients_sample(
        session,
        trainer_id,
        today,
        min_days=DORMANT_CLIENT_MIN_DAYS,
        limit=DORMANT_CLIENT_SAMPLE_LIMIT,
    )
    if dormant:
        return {
            "triggered": True,
            "consecutive_skip_days": skip_days,
            "case": 4,
            "case_key": "dormant_clients",
            "data": {"clients": dormant},
        }

    from src.application.trainer_use_cases import get_trainer_moderation_readiness

    readiness = await get_trainer_moderation_readiness(session, trainer_id)
    if readiness and not readiness.get("full_profile_complete"):
        return {
            "triggered": True,
            "consecutive_skip_days": skip_days,
            "case": 5,
            "case_key": "profile_incomplete",
            "data": {},
        }

    r_tpl = await session.execute(
        text(
            "SELECT COUNT(*)::int FROM trainer_schedule_templates WHERE trainer_id = :tid"
        ),
        {"tid": trainer_id},
    )
    tpl_row = r_tpl.fetchone()
    tpl_count = int(tpl_row[0]) if tpl_row and tpl_row[0] is not None else 0
    if tpl_count == 0:
        return {
            "triggered": True,
            "consecutive_skip_days": skip_days,
            "case": 6,
            "case_key": "no_weekly_template",
            "data": {},
        }

    return {
        "triggered": True,
        "consecutive_skip_days": skip_days,
        "case": 7,
        "case_key": "silence",
        "data": {},
    }


async def _consecutive_skip_days_before(
    session: AsyncSession, trainer_id: int, today: date
) -> int:
    """
    Count consecutive days with zero non-cancelled bookings, walking backward from yesterday.
    Stops at the first day with any non-cancelled booking. Upper bound = 14 days
    (beyond that drought is already obvious and signal strength plateaus).
    """
    max_lookback = 14
    r = await session.execute(
        text(
            """
            SELECT DISTINCT s.slot_date
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
              AND s.slot_date BETWEEN :d_from AND :d_to
            """
        ),
        {
            "tid": trainer_id,
            "d_from": today - timedelta(days=max_lookback),
            "d_to": today - timedelta(days=1),
        },
    )
    busy_days: set[date] = {row[0] for row in r.fetchall()}
    count = 0
    cur = today - timedelta(days=1)
    while count < max_lookback and cur not in busy_days:
        count += 1
        cur -= timedelta(days=1)
    return count


async def _dormant_clients_sample(
    session: AsyncSession,
    trainer_id: int,
    today: date,
    *,
    min_days: int,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Up to ``limit`` clients who had at least one completed session with trainer more than
    ``min_days`` ago and have no future non-cancelled bookings. Most-recent-last first.
    """
    r = await session.execute(
        text(
            """
            SELECT c.id,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   MAX(s.slot_date) AS last_completed_date
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            WHERE b.trainer_id = :tid
              AND b.status = 'completed'
              AND s.slot_date < :cutoff
              AND NOT EXISTS (
                  SELECT 1 FROM bookings b_fut
                  JOIN slots s_fut ON s_fut.id = b_fut.slot_id
                  WHERE b_fut.trainer_id = :tid
                    AND b_fut.client_id = c.id
                    AND b_fut.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                    AND s_fut.slot_date >= :today
              )
            GROUP BY c.id, client_name
            ORDER BY last_completed_date DESC, c.id ASC
            LIMIT :lim
            """
        ),
        {
            "tid": trainer_id,
            "cutoff": today - timedelta(days=min_days),
            "today": today,
            "lim": limit,
        },
    )
    return [
        {
            "client_id": int(row[0]),
            "client_name": (row[1] or "").strip() or "Клиент",
            "last_completed_date": row[2],
        }
        for row in r.fetchall()
    ]


# =============================================================================
# Scheduler helper: when to fire today's morning digest
# =============================================================================


def resolve_digest_send_time(
    *,
    digest_send_time: Optional[time],
    first_session_start: Optional[time],
    push_window_start_hour: int,
    push_window_end_hour: int,
    lead_minutes: int = 60,
) -> Optional[time]:
    """
    Europe/Minsk wall-clock time when today's **daily** digest should fire.

    Priority:
      1. Explicit ``digest_send_time`` from trainer settings (always honored).
      2. Auto: ``min(MORNING_DIGEST_AUTO_DEFAULT_T, first_session_start - lead_minutes)``
         when there is a session today; otherwise default morning time only.
         So a single evening workout no longer moves the digest to late afternoon.

    Clamped to ``[push_window_start_hour, push_window_end_hour)``.
    If the clamped time falls on or after the window end, returns None.
    """
    if digest_send_time is not None:
        return digest_send_time

    default_morning = MORNING_DIGEST_AUTO_DEFAULT_T

    if first_session_start is None:
        candidate = default_morning
    else:
        total = (
            first_session_start.hour * 60
            + first_session_start.minute
            - lead_minutes
        )
        if total < 0:
            total = 0
        pre_session = time(hour=total // 60, minute=total % 60)
        candidate = pre_session if pre_session < default_morning else default_morning

    lower = time(hour=push_window_start_hour)
    upper = time(hour=push_window_end_hour) if push_window_end_hour < 24 else None

    if candidate < lower:
        candidate = lower
    if upper is not None and candidate >= upper:
        return None

    return candidate


def resolve_weekly_digest_send_time(
    *,
    push_window_start_hour: int,
    push_window_end_hour: int,
) -> time:
    """
    Wall-clock moment for **Sunday weekly** Telegram digest (Europe/Minsk).

    Fixed evening default (~20:00); ``digest_send_time`` does **not** apply here (that knob is daily).
    Same-day push window clamp: ``[start_h, end_h)`` — if default hits the excluded end hour,
    target the last feasible hour inside the window.
    """
    candidate = WEEKLY_DIGEST_DEFAULT_SEND_T
    lower = time(hour=push_window_start_hour)
    upper = time(hour=push_window_end_hour) if push_window_end_hour < 24 else None

    if candidate < lower:
        candidate = lower

    if upper is not None and candidate >= upper:
        h = push_window_end_hour - 1
        if h < push_window_start_hour:
            candidate = lower
        else:
            candidate = time(hour=h, minute=0)

    return candidate


def now_minsk() -> datetime:
    """Current Europe/Minsk wall-clock time (scheduler convenience)."""
    return datetime.now(ZoneInfo(NOTIFICATION_TZ))


__all__ = [
    "get_trainer_daily_digest",
    "get_trainer_weekly_digest",
    "resolve_digest_send_time",
    "resolve_weekly_digest_send_time",
    "now_minsk",
    "GAP_MIN_MINUTES",
    "DROUGHT_CONSECUTIVE_DAYS",
    "DORMANT_CLIENT_MIN_DAYS",
    "DORMANT_CLIENT_SAMPLE_LIMIT",
    "DROUGHT_SLOT_HORIZON_DAYS",
]
