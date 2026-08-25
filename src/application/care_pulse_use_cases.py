"""
Care pulse — silence-aware presence check-in for trainers and clients.

Operational pushes (booking, reminder, digest) already keep the bot in the chat
when there is real work. This module fills the *quiet* gap so Ice Pro does not
disappear in Telegram — without competing with those messages.

Rules (keep this small):
- At most one pulse per recipient per cooldown.
- Never send on a day the trainer already got a digest.
- Never stack on a recent inactive-client nudge.
- First honest fact wins; if there is nothing true to say, stay silent
  (except a Wednesday quiet check-in for trainers).
- Copy lives in ``src/bot/messages.py``; delivery in ``notification_loops``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from src.infrastructure.db.models import (
    CARE_PULSE_AUDIENCE_CLIENT,
    CARE_PULSE_AUDIENCE_TRAINER,
    CARE_PULSE_KIND_CONFIRMED_BOOKING,
    CARE_PULSE_KIND_INVITE_BACK,
    CARE_PULSE_KIND_OPEN_SLOTS,
    CARE_PULSE_KIND_QUIET_CHECKIN,
    CARE_PULSE_KIND_TOMORROW_PLAN,
    CarePulse,
)
from src.shared.notification_hours import NOTIFICATION_TZ

# Lunch window: after morning digest (~08:00), before evening weekly (~20:00) and
# client evening-prior reminders. Not urgent — never fire at night even if quiet hours are bypassed.
CARE_PULSE_START_HOUR = 12
CARE_PULSE_END_HOUR = 14

TRAINER_COOLDOWN_HOURS = 48
TRAINER_QUIET_COOLDOWN_HOURS = 72
CLIENT_COOLDOWN_HOURS = 72

# Confirmed-booking pulse: 2–5 days out (0–1 is reminder territory).
CLIENT_CONFIRMED_MIN_DAYS = 2
CLIENT_CONFIRMED_MAX_DAYS = 5

# Invite-back for clients: after last session, before the 10-day inactive loop.
CLIENT_INVITE_MIN_DAYS = 4
CLIENT_INVITE_MAX_DAYS = 9

TRAINER_OPEN_SLOTS_MIN = 3
TRAINER_DORMANT_MIN_DAYS = 14
# Wednesday = 2 (Mon=0). Quiet check-in only this day so it is weekly, not every 48h.
QUIET_CHECKIN_WEEKDAY_MON0 = 2

_BATCH_LIMIT = 80


@dataclass(frozen=True, slots=True)
class CarePulseChoice:
    """Pure picker result — no DB, no Telegram."""

    kind: str
    context_key: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReadyCarePulse:
    """One message ready for delivery."""

    audience: str
    recipient_id: int
    telegram_id: int
    kind: str
    context_key: str
    payload: dict[str, Any]


def is_within_care_pulse_window(now_minsk: datetime) -> bool:
    """True in [12:00, 14:00) Europe/Minsk. Presence is not 24/7 work."""
    hour = now_minsk.astimezone(ZoneInfo(NOTIFICATION_TZ)).hour if now_minsk.tzinfo else now_minsk.hour
    return CARE_PULSE_START_HOUR <= hour < CARE_PULSE_END_HOUR


def _hours_since(last_at: Optional[datetime], now: datetime) -> Optional[float]:
    if last_at is None:
        return None
    last = last_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return (current - last).total_seconds() / 3600.0


def pick_trainer_pulse(
    *,
    digest_sent_today: bool,
    hours_since_last_pulse: Optional[float],
    weekday_mon0: int,
    tomorrow_sessions: int,
    tomorrow_first_time: Optional[time],
    tomorrow_first_name: str,
    open_slots_7d: int,
    dormant_name: str,
    dormant_days: Optional[int],
    today_iso: str,
) -> Optional[CarePulseChoice]:
    """First honest fact wins. Silence is a valid outcome."""
    if digest_sent_today:
        return None
    if weekday_mon0 == 6:
        # Sunday belongs to the weekly digest, not a lunch check-in.
        return None
    if hours_since_last_pulse is not None and hours_since_last_pulse < TRAINER_COOLDOWN_HOURS:
        return None

    if tomorrow_sessions >= 1:
        return CarePulseChoice(
            kind=CARE_PULSE_KIND_TOMORROW_PLAN,
            context_key=today_iso,
            payload={
                "sessions_count": tomorrow_sessions,
                "first_time": tomorrow_first_time,
                "first_name": (tomorrow_first_name or "").strip(),
            },
        )
    if open_slots_7d >= TRAINER_OPEN_SLOTS_MIN:
        return CarePulseChoice(
            kind=CARE_PULSE_KIND_OPEN_SLOTS,
            context_key=today_iso,
            payload={"open_slots": open_slots_7d},
        )
    if dormant_name and dormant_days is not None and dormant_days >= TRAINER_DORMANT_MIN_DAYS:
        return CarePulseChoice(
            kind=CARE_PULSE_KIND_INVITE_BACK,
            context_key=today_iso,
            payload={"name": dormant_name, "days": dormant_days},
        )
    if weekday_mon0 == QUIET_CHECKIN_WEEKDAY_MON0:
        if hours_since_last_pulse is None or hours_since_last_pulse >= TRAINER_QUIET_COOLDOWN_HOURS:
            return CarePulseChoice(
                kind=CARE_PULSE_KIND_QUIET_CHECKIN,
                context_key=today_iso,
                payload={},
            )
    return None


def pick_client_pulse(
    *,
    hours_since_last_pulse: Optional[float],
    inactive_sent_recent: bool,
    days_until_upcoming: Optional[int],
    upcoming_booking_id: Optional[int],
    upcoming_date: Optional[date],
    upcoming_time: Optional[time],
    upcoming_trainer_name: str,
    upcoming_arena_name: str,
    has_future_booking: bool,
    days_since_last_completed: Optional[int],
    last_trainer_name: str,
    today_iso: str,
) -> Optional[CarePulseChoice]:
    if inactive_sent_recent:
        return None
    if hours_since_last_pulse is not None and hours_since_last_pulse < CLIENT_COOLDOWN_HOURS:
        return None

    if (
        upcoming_booking_id is not None
        and days_until_upcoming is not None
        and CLIENT_CONFIRMED_MIN_DAYS <= days_until_upcoming <= CLIENT_CONFIRMED_MAX_DAYS
    ):
        return CarePulseChoice(
            kind=CARE_PULSE_KIND_CONFIRMED_BOOKING,
            context_key=f"b:{int(upcoming_booking_id)}",
            payload={
                "slot_date": upcoming_date,
                "start_time": upcoming_time,
                "trainer_name": (upcoming_trainer_name or "").strip(),
                "arena_name": (upcoming_arena_name or "").strip(),
            },
        )

    if (
        not has_future_booking
        and days_since_last_completed is not None
        and CLIENT_INVITE_MIN_DAYS <= days_since_last_completed <= CLIENT_INVITE_MAX_DAYS
    ):
        return CarePulseChoice(
            kind=CARE_PULSE_KIND_INVITE_BACK,
            context_key=today_iso,
            payload={"trainer_name": (last_trainer_name or "").strip()},
        )
    return None


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_time(value: Any) -> Optional[time]:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    text_v = str(value)
    if len(text_v) >= 5 and text_v[2] == ":":
        hh, mm = int(text_v[:2]), int(text_v[3:5])
        return time(hh, mm)
    return None


async def list_due_care_pulses(
    session: AsyncSession,
    now_minsk: datetime,
    *,
    limit: int = _BATCH_LIMIT,
) -> list[ReadyCarePulse]:
    """Load facts and pick pulses. No writes."""
    today = now_minsk.date()
    today_iso = today.isoformat()
    weekday_mon0 = today.weekday()
    trainers = await _list_trainer_facts(session, now_minsk, today, limit=limit)
    clients = await _list_client_facts(session, now_minsk, today, limit=limit)
    out: list[ReadyCarePulse] = []

    for row in trainers:
        choice = pick_trainer_pulse(
            digest_sent_today=bool(row["digest_sent_today"]),
            hours_since_last_pulse=row["hours_since_last_pulse"],
            weekday_mon0=weekday_mon0,
            tomorrow_sessions=int(row["tomorrow_sessions"] or 0),
            tomorrow_first_time=row["tomorrow_first_time"],
            tomorrow_first_name=str(row["tomorrow_first_name"] or ""),
            open_slots_7d=int(row["open_slots_7d"] or 0),
            dormant_name=str(row["dormant_name"] or ""),
            dormant_days=row["dormant_days"],
            today_iso=today_iso,
        )
        if choice is None:
            continue
        out.append(
            ReadyCarePulse(
                audience=CARE_PULSE_AUDIENCE_TRAINER,
                recipient_id=int(row["trainer_id"]),
                telegram_id=int(row["telegram_id"]),
                kind=choice.kind,
                context_key=choice.context_key,
                payload=choice.payload,
            )
        )

    for row in clients:
        upcoming_date = row["upcoming_date"]
        days_until = None
        if upcoming_date is not None:
            days_until = (upcoming_date - today).days
        last_date = row["last_completed_date"]
        days_since = None
        if last_date is not None:
            days_since = (today - last_date).days
        choice = pick_client_pulse(
            hours_since_last_pulse=row["hours_since_last_pulse"],
            inactive_sent_recent=bool(row["inactive_sent_recent"]),
            days_until_upcoming=days_until,
            upcoming_booking_id=row["upcoming_booking_id"],
            upcoming_date=upcoming_date,
            upcoming_time=row["upcoming_time"],
            upcoming_trainer_name=str(row["upcoming_trainer_name"] or ""),
            upcoming_arena_name=str(row["upcoming_arena_name"] or ""),
            has_future_booking=bool(row["has_future_booking"]),
            days_since_last_completed=days_since,
            last_trainer_name=str(row["last_trainer_name"] or ""),
            today_iso=today_iso,
        )
        if choice is None:
            continue
        out.append(
            ReadyCarePulse(
                audience=CARE_PULSE_AUDIENCE_CLIENT,
                recipient_id=int(row["client_id"]),
                telegram_id=int(row["telegram_id"]),
                kind=choice.kind,
                context_key=choice.context_key,
                payload=choice.payload,
            )
        )
    return out


async def _list_trainer_facts(
    session: AsyncSession,
    now_minsk: datetime,
    today: date,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    tomorrow = today + timedelta(days=1)
    horizon = today + timedelta(days=7)
    cutoff = now_minsk - timedelta(hours=TRAINER_COOLDOWN_HOURS)
    dormant_cutoff = today - timedelta(days=TRAINER_DORMANT_MIN_DAYS)
    r = await session.execute(
        text(
            """
            WITH last_pulse AS (
                SELECT recipient_id, MAX(sent_at) AS last_at
                FROM care_pulses
                WHERE audience = 'trainer'
                GROUP BY recipient_id
            ),
            tomorrow_agg AS (
                SELECT b.trainer_id,
                       COUNT(*)::int AS sessions,
                       MIN(s.start_time) AS first_time,
                       (
                           ARRAY_AGG(
                               TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, ''))
                               ORDER BY s.start_time, b.id
                           )
                       )[1] AS first_name
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                JOIN clients c ON c.id = b.client_id
                WHERE b.status IN ('pending', 'confirmed')
                  AND NOT b.is_sandbox
                  AND s.slot_date = :tomorrow
                  AND s.status IN ('available', 'booked')
                GROUP BY b.trainer_id
            ),
            open_slots AS (
                SELECT s.trainer_id, COUNT(*)::int AS n
                FROM slots s
                WHERE s.status = 'available'
                  AND s.slot_date BETWEEN :today AND :horizon
                  AND (
                      s.capacity - (
                          SELECT COUNT(*) FROM bookings b
                          WHERE b.slot_id = s.id
                            AND b.status IN ('pending', 'confirmed')
                            AND NOT b.is_sandbox
                      )
                  ) > 0
                GROUP BY s.trainer_id
            )
            SELECT t.id,
                   t.telegram_id,
                   (ds.id IS NOT NULL) AS digest_sent_today,
                   lp.last_at,
                   COALESCE(ta.sessions, 0) AS tomorrow_sessions,
                   ta.first_time,
                   ta.first_name,
                   COALESCE(os.n, 0) AS open_slots_7d,
                   d.name AS dormant_name,
                   d.days AS dormant_days
            FROM trainers t
            LEFT JOIN last_pulse lp ON lp.recipient_id = t.id
            LEFT JOIN trainer_digest_sent ds
                ON ds.trainer_id = t.id AND ds.sent_date = :today
            LEFT JOIN tomorrow_agg ta ON ta.trainer_id = t.id
            LEFT JOIN open_slots os ON os.trainer_id = t.id
            LEFT JOIN LATERAL (
                SELECT TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS name,
                       (:today - MAX(s.slot_date))::int AS days
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                JOIN clients c ON c.id = b.client_id
                WHERE b.trainer_id = t.id
                  AND b.status = 'completed'
                  AND NOT b.is_sandbox
                  AND NOT c.is_sandbox
                  AND s.slot_date < :dormant_cutoff
                  AND NOT EXISTS (
                      SELECT 1 FROM bookings b_fut
                      JOIN slots s_fut ON s_fut.id = b_fut.slot_id
                      WHERE b_fut.trainer_id = t.id
                        AND b_fut.client_id = c.id
                        AND b_fut.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                        AND NOT b_fut.is_sandbox
                        AND s_fut.slot_date >= :today
                  )
                GROUP BY c.id, c.first_name, c.last_name
                ORDER BY MAX(s.slot_date) DESC, c.id ASC
                LIMIT 1
            ) d ON true
            WHERE t.status = 'active'
              AND t.telegram_id IS NOT NULL
              AND (lp.last_at IS NULL OR lp.last_at < :cutoff)
            ORDER BY t.id
            LIMIT :lim
            """
        ),
        {
            "today": today,
            "tomorrow": tomorrow,
            "horizon": horizon,
            "cutoff": cutoff,
            "dormant_cutoff": dormant_cutoff,
            "lim": limit,
        },
    )
    now = now_minsk if now_minsk.tzinfo else now_minsk.replace(tzinfo=ZoneInfo(NOTIFICATION_TZ))
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        last_at = row[3]
        dormant_days = int(row[9]) if row[9] is not None else None
        out.append(
            {
                "trainer_id": int(row[0]),
                "telegram_id": int(row[1]),
                "digest_sent_today": bool(row[2]),
                "hours_since_last_pulse": _hours_since(last_at, now),
                "tomorrow_sessions": int(row[4] or 0),
                "tomorrow_first_time": _as_time(row[5]),
                "tomorrow_first_name": (row[6] or "").strip(),
                "open_slots_7d": int(row[7] or 0),
                "dormant_name": (row[8] or "").strip(),
                "dormant_days": dormant_days,
            }
        )
    return out


async def _list_client_facts(
    session: AsyncSession,
    now_minsk: datetime,
    today: date,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    cutoff = now_minsk - timedelta(hours=CLIENT_COOLDOWN_HOURS)
    inactive_cutoff = now_minsk - timedelta(days=14)
    from_d = today + timedelta(days=CLIENT_CONFIRMED_MIN_DAYS)
    to_d = today + timedelta(days=CLIENT_CONFIRMED_MAX_DAYS)
    invite_from = today - timedelta(days=CLIENT_INVITE_MAX_DAYS)
    invite_to = today - timedelta(days=CLIENT_INVITE_MIN_DAYS)
    r = await session.execute(
        text(
            """
            WITH last_pulse AS (
                SELECT recipient_id, MAX(sent_at) AS last_at
                FROM care_pulses
                WHERE audience = 'client'
                GROUP BY recipient_id
            ),
            eligible AS (
                SELECT c.id, c.telegram_id, lp.last_at,
                       EXISTS (
                           SELECT 1 FROM client_inactive_notifications n
                           WHERE n.client_id = c.id AND n.sent_at > :inactive_cutoff
                       ) AS inactive_sent_recent
                FROM clients c
                LEFT JOIN last_pulse lp ON lp.recipient_id = c.id
                WHERE c.telegram_id IS NOT NULL
                  AND c.is_sandbox = false
                  AND (lp.last_at IS NULL OR lp.last_at < :cutoff)
            ),
            upcoming AS (
                SELECT DISTINCT ON (b.client_id)
                    b.client_id,
                    b.id AS booking_id,
                    s.slot_date,
                    s.start_time,
                    TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')) AS trainer_name,
                    a.name AS arena_name
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
                LEFT JOIN arenas a ON a.id = COALESCE(b.arena_id, s.arena_id)
                WHERE b.status IN ('pending', 'confirmed')
                  AND NOT b.is_sandbox
                  AND s.status IN ('available', 'booked')
                  AND s.slot_date BETWEEN :from_d AND :to_d
                ORDER BY b.client_id, s.slot_date, s.start_time, b.id
            ),
            last_done AS (
                SELECT DISTINCT ON (b.client_id)
                    b.client_id,
                    s.slot_date AS last_date,
                    TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')) AS trainer_name
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
                WHERE b.status = 'completed'
                  AND NOT b.is_sandbox
                ORDER BY b.client_id, s.slot_date DESC, s.start_time DESC, b.id DESC
            ),
            has_future AS (
                SELECT DISTINCT b.client_id
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.status IN ('pending', 'confirmed')
                  AND NOT b.is_sandbox
                  AND s.status IN ('available', 'booked')
                  AND s.slot_date >= :today
            )
            SELECT e.id,
                   e.telegram_id,
                   e.last_at,
                   e.inactive_sent_recent,
                   u.booking_id,
                   u.slot_date,
                   u.start_time,
                   u.trainer_name,
                   u.arena_name,
                   ld.last_date,
                   ld.trainer_name AS last_trainer_name,
                   (hf.client_id IS NOT NULL) AS has_future
            FROM eligible e
            LEFT JOIN upcoming u ON u.client_id = e.id
            LEFT JOIN last_done ld ON ld.client_id = e.id
            LEFT JOIN has_future hf ON hf.client_id = e.id
            WHERE u.booking_id IS NOT NULL
               OR (
                   hf.client_id IS NULL
                   AND ld.last_date IS NOT NULL
                   AND ld.last_date BETWEEN :invite_from AND :invite_to
               )
            ORDER BY e.id
            LIMIT :lim
            """
        ),
        {
            "cutoff": cutoff,
            "inactive_cutoff": inactive_cutoff,
            "from_d": from_d,
            "to_d": to_d,
            "today": today,
            "invite_from": invite_from,
            "invite_to": invite_to,
            "lim": limit,
        },
    )
    now = now_minsk if now_minsk.tzinfo else now_minsk.replace(tzinfo=ZoneInfo(NOTIFICATION_TZ))
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        out.append(
            {
                "client_id": int(row[0]),
                "telegram_id": int(row[1]),
                "hours_since_last_pulse": _hours_since(row[2], now),
                "inactive_sent_recent": bool(row[3]),
                "upcoming_booking_id": int(row[4]) if row[4] is not None else None,
                "upcoming_date": _as_date(row[5]),
                "upcoming_time": _as_time(row[6]),
                "upcoming_trainer_name": (row[7] or "").strip(),
                "upcoming_arena_name": (row[8] or "").strip(),
                "last_completed_date": _as_date(row[9]),
                "last_trainer_name": (row[10] or "").strip(),
                "has_future_booking": bool(row[11]),
            }
        )
    return out


async def claim_care_pulse(
    session: AsyncSession,
    *,
    audience: str,
    recipient_id: int,
    kind: str,
    context_key: str,
) -> bool:
    """Insert idempotency row. True if this worker won the claim."""
    stmt = (
        pg_insert(CarePulse)
        .values(
            audience=audience,
            recipient_id=recipient_id,
            kind=kind,
            context_key=context_key[:64],
        )
        .on_conflict_do_nothing(
            constraint="uq_care_pulses_audience_recipient_kind_ctx",
        )
    )
    result = await session.execute(stmt)
    await session.commit()
    return bool(result.rowcount and result.rowcount > 0)


__all__ = [
    "CARE_PULSE_END_HOUR",
    "CARE_PULSE_START_HOUR",
    "CarePulseChoice",
    "ReadyCarePulse",
    "claim_care_pulse",
    "is_within_care_pulse_window",
    "list_due_care_pulses",
    "pick_client_pulse",
    "pick_trainer_pulse",
]
