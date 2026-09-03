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


def sql_trainer_has_real_booking(*, trainer_id_expr: str = "t.id") -> str:
    """
    SQL boolean: this trainer's "first real booking" milestone — true once, never regresses.

    Backed by ``trainer_profiles.first_booking_milestone_at`` (set atomically the moment a
    real, non-sandbox booking first reaches confirmed/completed, and never cleared — see
    ``trainer_first_booking_milestone.py``) OR a currently-live real booking. The milestone
    column alone would miss a trainer whose profile row doesn't exist yet, or whose only
    booking is still ``pending`` (not yet claimed); the live-booking check alone would
    regress to false the moment a completed booking is later cancelled (TASK-027 AC-005).

    ``trainer_id_expr`` is a raw SQL expression evaluating to the trainer id — a joined
    alias's column (``t.id``, the default) or a bind parameter (``:tid``). Unlike
    ``sql_trainer_shared_client_invite``/``sql_trainer_submitted_for_moderation`` above,
    this fragment never reads another ``trainers`` column, so it takes the id directly
    rather than an alias to append ``.id`` to.
    """
    tid = trainer_id_expr
    return f"""(
  EXISTS (
    SELECT 1 FROM trainer_profiles tp
    WHERE tp.trainer_id = {tid} AND tp.first_booking_milestone_at IS NOT NULL
  )
  OR EXISTS (
    SELECT 1 FROM bookings b
    WHERE b.trainer_id = {tid}
      AND COALESCE(b.is_sandbox, false) = false
      AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
  )
)"""


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
    from src.application.trainer_feature_tracking import FEATURE_SHARE_LINK, record_feature_first_use

    await record_feature_first_use(session, trainer_id, FEATURE_SHARE_LINK)
    await session.commit()
    return ts
