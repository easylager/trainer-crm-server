"""Online ticket link for client booking Telegram copy (TASK-293)."""
from __future__ import annotations

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
