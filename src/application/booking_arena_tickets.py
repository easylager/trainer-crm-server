"""Online ticket link for client booking Telegram copy (TASK-293)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.html_template import safe_external_url

_ARENA_TICKETS_URL_SQL = """
SELECT NULLIF(TRIM(ap.tickets_url), '')
FROM arena_profiles ap
WHERE ap.arena_id = :arena_id
"""


async def fetch_arena_tickets_url(session: AsyncSession, arena_id: int | None) -> str | None:
    """``arena_profiles.tickets_url`` as a safe https link, or None."""
    if arena_id is None:
        return None
    raw = (await session.execute(text(_ARENA_TICKETS_URL_SQL), {"arena_id": int(arena_id)})).scalar()
    return safe_external_url(raw)


async def enrich_booking_notification_with_arena_tickets(
    session: AsyncSession,
    info: dict[str, Any],
    *,
    arena_id_key: str = "resolved_arena_id",
    online_key: str = "service_is_online",
) -> None:
    """Sets ``info["arena_tickets_url"]``; online services never get a ticket link."""
    if info.get(online_key):
        info["arena_tickets_url"] = None
        return
    info["arena_tickets_url"] = await fetch_arena_tickets_url(session, info.get(arena_id_key))



async def fetch_booking_tickets_url(session: AsyncSession, booking_id: int) -> str | None:
    """Ticket link for a booking's rink (same arena resolution as client pushes); None for online services."""
    from src.application.booking_use_cases import SQL_BOOKING_RESOLVED_ARENA_ID_FOR_CLIENT

    arena_id = (
        await session.execute(
            text(
                "SELECT (" + SQL_BOOKING_RESOLVED_ARENA_ID_FOR_CLIENT + ") FROM bookings b "
                "JOIN slots s ON s.id = b.slot_id "
                "LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id "
                "WHERE b.id = :bid"
            ),
            {"bid": int(booking_id)},
        )
    ).scalar()
    return await fetch_arena_tickets_url(session, arena_id)

# Korona snapshots arrive every ~15 min; an older one may already be sold out.
TICKET_SNAPSHOT_MAX_AGE = timedelta(minutes=45)

_TICKET_AVAILABILITY_SQL = """
SELECT capacity, GREATEST(capacity - sold - held, 0) AS free
FROM ice_sales_snapshots
WHERE arena_id = :arena_id
  AND local_date = :local_date
  AND starts_at_local <= CAST(:start_time AS time)
  AND starts_at_local > CAST(:start_time AS time) - INTERVAL '60 minutes'
  AND observed_at >= :fresh_since
ORDER BY starts_at_local DESC, observed_at DESC
LIMIT 1
"""


@dataclass(frozen=True)
class TicketAvailability:
    free: int
    capacity: int


async def fetch_ticket_availability(
    session: AsyncSession,
    arena_id: int | None,
    local_date: date | None,
    start_time: time | None,
    *,
    now: datetime | None = None,
) -> TicketAvailability | None:
    """Free seats on the rink's public session covering ``start_time``, from a fresh Korona snapshot."""
    if arena_id is None or local_date is None or start_time is None:
        return None
    fresh_since = (now or datetime.now(timezone.utc)) - TICKET_SNAPSHOT_MAX_AGE
    row = (
        await session.execute(
            text(_TICKET_AVAILABILITY_SQL),
            {
                "arena_id": int(arena_id),
                "local_date": local_date,
                "start_time": start_time,
                "fresh_since": fresh_since,
            },
        )
    ).first()
    if row is None or not row[0]:
        return None
    return TicketAvailability(free=int(row[1]), capacity=int(row[0]))
