"""
One-time funnel after the trainer's first confirmed/completed booking.

Uses atomic UPDATEs so concurrent first bookings only claim once; flags persist if the
booking is later cancelled (no repeat celebration).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def try_claim_first_booking_milestones(session: AsyncSession, trainer_id: int) -> tuple[bool, bool]:
    """
    If this trainer now has exactly one confirmed/completed booking and profile flags
    are still unset, set first_booking_milestone_at; then set share_catalog_tip_sent_at.

    Returns (claimed_congrats, claimed_tip) for the current transaction only.
    Caller must commit when either is True.
    """
    r1 = await session.execute(
        text(
            """
            UPDATE trainer_profiles tp
            SET first_booking_milestone_at = NOW()
            WHERE tp.trainer_id = :tid
              AND tp.first_booking_milestone_at IS NULL
              AND (
                SELECT COUNT(*)::int FROM bookings b
                WHERE b.trainer_id = :tid
                  AND b.status IN ('confirmed', 'completed')
              ) = 1
            RETURNING tp.trainer_id
            """
        ),
        {"tid": trainer_id},
    )
    claimed_congrats = r1.fetchone() is not None
    claimed_tip = False
    if claimed_congrats:
        r2 = await session.execute(
            text(
                """
                UPDATE trainer_profiles tp
                SET share_catalog_tip_sent_at = NOW()
                WHERE tp.trainer_id = :tid
                  AND tp.share_catalog_tip_sent_at IS NULL
                RETURNING tp.trainer_id
                """
            ),
            {"tid": trainer_id},
        )
        claimed_tip = r2.fetchone() is not None
    return claimed_congrats, claimed_tip


async def count_confirmed_or_completed_bookings(session: AsyncSession, trainer_id: int) -> int:
    """Count bookings in terminal active states (for tests / diagnostics)."""
    r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int FROM bookings
            WHERE trainer_id = :tid AND status IN ('confirmed', 'completed')
            """
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    return int(row[0]) if row and row[0] is not None else 0
