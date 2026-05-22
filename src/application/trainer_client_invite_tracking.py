"""Track first client invite / share-link copy for admin activation funnel."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def sql_trainer_shared_client_invite(*, trainer_alias: str = "t") -> str:
    """
    SQL boolean: trainer copied a client invite link or has evidence of client outreach.
    Used in admin funnels when clipboard tracking missed (pre-migration, WebView quirks).
    """
    ta = trainer_alias
    return f"""(
  {ta}.client_invite_link_first_copied_at IS NOT NULL
  OR EXISTS (
    SELECT 1
    FROM trainer_client_roster r
    JOIN clients c ON c.id = r.client_id
    WHERE r.trainer_id = {ta}.id
      AND c.telegram_id IS NOT NULL
      AND COALESCE(c.is_sandbox, false) = false
  )
  OR EXISTS (
    SELECT 1 FROM bookings b
    WHERE b.trainer_id = {ta}.id
      AND COALESCE(b.is_sandbox, false) = false
      AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
  )
)"""


def sql_trainer_submitted_for_moderation(*, trainer_alias: str = "t") -> str:
    """SQL boolean: profile was submitted or trainer already passed moderation (active)."""
    ta = trainer_alias
    return f"({ta}.moderation_submitted_at IS NOT NULL OR {ta}.status = 'active')"


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
    ts = row[0]
    await session.commit()
    return ts
