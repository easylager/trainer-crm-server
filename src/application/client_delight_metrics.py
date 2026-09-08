"""
Metrics behind EPIC4 gate G-P5 — «хочется вернуться и показать» (TASK-096).

Two numbers, deliberately separate:

* :func:`get_second_booking_within_7d` — the **return** metric the owner chose: of the clients
  whose first-ever booking fell inside the window, what share made a second one within 7 days
  of that first. Reads existing ``bookings`` rows, so a baseline can be taken retroactively —
  no instrumentation, no waiting for data to accumulate.
* :func:`get_share_counts` — the **share** metric G-P5 also demands ("и это измеряется"),
  read from ``client_share_events``. This one starts at zero by construction: nothing was
  recorded before TASK-096, and saying otherwise would be inventing history.

Both return plain dicts of ints/floats. No formatting, no copy — callers present.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Bookings that never happened must not count as a return. A cancelled or declined second
# booking is not a second visit; excluding them keeps the metric honest in the pessimistic
# direction, which is the only safe direction for a gate.
COUNTED_BOOKING_STATUSES = ("pending", "confirmed", "completed", "no_show")

RETURN_WINDOW_DAYS = 7

# Default cohort window for a baseline: a quarter is long enough that a young product has
# any first bookings at all, and short enough to still describe the current product.
DEFAULT_COHORT_DAYS = 90


def _statuses_sql_list() -> str:
    return ", ".join(f"'{s}'" for s in COUNTED_BOOKING_STATUSES)


async def get_second_booking_within_7d(
    session: AsyncSession,
    *,
    as_of: datetime | date | None = None,
    cohort_days: int = DEFAULT_COHORT_DAYS,
) -> dict:
    """
    Share of clients who booked a second time within 7 days of their first booking.

    The cohort is clients whose **first-ever** booking is inside
    ``[as_of - cohort_days, as_of - 7 days]``. The right edge matters: a client whose first
    booking was yesterday has not had seven days to come back, and counting them as a
    failure would drag the number down for no reason. ``pending_cohort`` reports how many
    are still inside their window, so the exclusion is visible rather than silent.

    Sandbox (onboarding demo) bookings are excluded — they are not client behaviour.
    """
    if cohort_days < RETURN_WINDOW_DAYS + 1:
        raise ValueError(
            f"cohort_days must exceed the {RETURN_WINDOW_DAYS}-day return window, got {cohort_days}"
        )

    if as_of is None:
        as_of_dt = datetime.now(timezone.utc)
    elif isinstance(as_of, datetime):
        as_of_dt = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    else:
        as_of_dt = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)

    cohort_start = as_of_dt - timedelta(days=cohort_days)
    cohort_end = as_of_dt - timedelta(days=RETURN_WINDOW_DAYS)
    statuses = _statuses_sql_list()

    rows = await session.execute(
        text(
            f"""
            WITH counted AS (
                SELECT client_id, created_at
                FROM bookings
                WHERE status IN ({statuses})
                  AND is_sandbox = false
            ),
            firsts AS (
                SELECT client_id, MIN(created_at) AS first_at
                FROM counted
                GROUP BY client_id
            ),
            cohort AS (
                SELECT client_id, first_at
                FROM firsts
                WHERE first_at >= :cohort_start
                  AND first_at < :cohort_end
            )
            SELECT
                (SELECT COUNT(*) FROM cohort) AS cohort_size,
                (
                    SELECT COUNT(*) FROM cohort c
                    WHERE EXISTS (
                        SELECT 1 FROM counted b
                        WHERE b.client_id = c.client_id
                          AND b.created_at > c.first_at
                          AND b.created_at <= c.first_at + make_interval(days => :window_days)
                    )
                ) AS returned,
                (
                    SELECT COUNT(*) FROM firsts
                    WHERE first_at >= :cohort_end
                      AND first_at < :as_of
                ) AS pending_cohort
            """
        ),
        {
            "cohort_start": cohort_start,
            "cohort_end": cohort_end,
            "as_of": as_of_dt,
            "window_days": RETURN_WINDOW_DAYS,
        },
    )
    row = rows.fetchone()
    cohort_size = int(row[0] or 0) if row else 0
    returned = int(row[1] or 0) if row else 0
    pending = int(row[2] or 0) if row else 0

    return {
        "metric": "second_booking_within_7d",
        "as_of": as_of_dt.isoformat(),
        "cohort_days": cohort_days,
        "window_days": RETURN_WINDOW_DAYS,
        "cohort_start": cohort_start.isoformat(),
        "cohort_end": cohort_end.isoformat(),
        "cohort_size": cohort_size,
        "returned": returned,
        # None, not 0.0, when the cohort is empty — "we don't know" and "nobody returned"
        # are different facts and a gate must not confuse them.
        "rate_pct": round(100.0 * returned / cohort_size, 1) if cohort_size else None,
        "pending_cohort": pending,
    }


async def get_share_counts(
    session: AsyncSession,
    *,
    days: int = 30,
    as_of: datetime | None = None,
) -> dict:
    """Share events per kind in the last ``days``, plus distinct sharers per kind."""
    as_of_dt = as_of or datetime.now(timezone.utc)
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
    since = as_of_dt - timedelta(days=days)

    rows = await session.execute(
        text(
            """
            SELECT kind,
                   COUNT(*) AS events,
                   COUNT(DISTINCT actor_hash) AS sharers
            FROM client_share_events
            WHERE occurred_at >= :since AND occurred_at < :as_of
            GROUP BY kind
            ORDER BY kind
            """
        ),
        {"since": since, "as_of": as_of_dt},
    )
    by_kind = {
        str(r[0]): {"events": int(r[1] or 0), "sharers": int(r[2] or 0)} for r in rows.fetchall()
    }
    return {
        "metric": "client_shares",
        "as_of": as_of_dt.isoformat(),
        "days": days,
        "since": since.isoformat(),
        "by_kind": by_kind,
        "events_total": sum(v["events"] for v in by_kind.values()),
    }


def share_actor_hash(telegram_id: int | str | None, kind: str, day: date) -> str | None:
    """
    Irreversible per-day actor key. ``None`` in, ``None`` out — an anonymous share is still
    a share worth counting, it just doesn't contribute to the distinct-sharer count.
    """
    if telegram_id is None:
        return None
    raw = f"{telegram_id}|{kind}|{day.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def record_client_share(
    session: AsyncSession,
    *,
    kind: str,
    share_context: str | None = None,
    city_id: int | None = None,
    arena_id: int | None = None,
    trainer_id: int | None = None,
    telegram_id: int | str | None = None,
    payload: dict | None = None,
) -> None:
    """
    Append one share event. Never raises into the caller's request: a failed *measurement*
    must not break the *feature* being measured — the share dialog still has to open.
    """
    from src.infrastructure.db.models import CLIENT_SHARE_KINDS

    if kind not in CLIENT_SHARE_KINDS:
        raise ValueError(f"Unknown client share kind: {kind!r}")

    import json

    actor = share_actor_hash(telegram_id, kind, datetime.now(timezone.utc).date())
    try:
        await session.execute(
            text(
                """
                INSERT INTO client_share_events
                    (kind, share_context, city_id, arena_id, trainer_id, actor_hash, payload)
                VALUES
                    (:kind, :ctx, :city_id, :arena_id, :trainer_id, :actor, CAST(:payload AS jsonb))
                """
            ),
            {
                "kind": kind,
                "ctx": share_context or None,
                "city_id": city_id,
                "arena_id": arena_id,
                "trainer_id": trainer_id,
                "actor": actor,
                "payload": json.dumps(payload or {}, ensure_ascii=False),
            },
        )
        await session.commit()
    except Exception:  # noqa: BLE001 — telemetry is never worth a 500 on the share path
        await session.rollback()
