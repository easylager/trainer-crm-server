"""Track first client invite / share-link copy for admin activation funnel."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record_trainer_client_invite_link_first_copy(session: AsyncSession, trainer_id: int) -> datetime | None:
    """
    Idempotent: set trainers.client_invite_link_first_copied_at on first successful copy only.
    Used when trainer shares welcome link, per-client bind link, public booking link, or pass welcome URL.
    """
    r = await session.execute(
        text(
            """
            UPDATE trainers
            SET client_invite_link_first_copied_at = COALESCE(client_invite_link_first_copied_at, NOW())
            WHERE id = :tid
            RETURNING client_invite_link_first_copied_at
            """
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    if not row or row[0] is None:
        return None
    return row[0]
