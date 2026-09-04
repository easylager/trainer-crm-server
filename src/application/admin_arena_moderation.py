"""
Admin post-hoc moderation queue for trainer-created arenas (TASK-046).

Mirrors the shape of trainer profile moderation (``/pending`` + approve/reject in
``admin_handlers.py``) but is a separate, arena-scoped queue — arenas have no photo,
no education, no multi-field review, so they don't share the trainer moderation card.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_arenas_pending_moderation(session: AsyncSession) -> list[dict[str, Any]]:
    """Trainer-created arenas awaiting admin confirmation (AC-004), oldest first."""
    r = await session.execute(
        text(
            """
            SELECT a.id, a.name, a.address, a.latitude, a.longitude,
                   c.name AS city_name,
                   t.id AS trainer_id, t.telegram_id AS trainer_telegram_id,
                   tp.first_name, tp.last_name
            FROM arenas a
            JOIN cities c ON c.id = a.city_id
            LEFT JOIN trainers t ON t.id = a.created_by_trainer_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE a.is_active AND NOT a.is_confirmed
            ORDER BY a.id
            """
        )
    )
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        trainer_name = " ".join(p for p in [row[8], row[9]] if p).strip() or None
        out.append(
            {
                "id": row[0],
                "name": row[1],
                "address": row[2],
                "latitude": row[3],
                "longitude": row[4],
                "city_name": row[5],
                "trainer_id": row[6],
                "trainer_telegram_id": row[7],
                "trainer_name": trainer_name,
            }
        )
    return out


async def approve_arena(session: AsyncSession, arena_id: int, admin_id: int) -> bool:
    """Confirm a trainer-created arena — makes it visible in the public client catalog."""
    r = await session.execute(
        text(
            """
            UPDATE arenas
            SET is_confirmed = true, confirmed_at = :now, confirmed_by_admin_id = :admin_id
            WHERE id = :id AND is_active
            """
        ),
        {"id": arena_id, "now": datetime.now(timezone.utc), "admin_id": admin_id},
    )
    await session.commit()
    return r.rowcount > 0


async def reject_arena(session: AsyncSession, arena_id: int) -> bool:
    """
    Deactivate a rejected arena unconditionally (AC-007) — even if one or more trainers
    already selected and are using it in their schedule (EDGE-003: their existing
    slots/templates keep referencing the now-inactive arena; not cleaned up here).
    """
    r = await session.execute(
        text("UPDATE arenas SET is_active = false WHERE id = :id"),
        {"id": arena_id},
    )
    await session.commit()
    return r.rowcount > 0
