"""Payment / pass / certificate deduction facts for session-end Telegram notices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DeductionOutcome = Literal["pass", "cert", "none"]


@dataclass(frozen=True)
class BookingDeductionSnapshot:
    """Actual ledger state after booking completion (pass_redemptions / certificate_booking_credits)."""

    outcome: DeductionOutcome
    pass_sessions_remaining: int | None = None
    cert_amount_cents: int | None = None
    cert_remaining_cents: int | None = None


async def load_booking_deduction_snapshot(
    session: AsyncSession,
    booking_id: int,
) -> BookingDeductionSnapshot:
    """Return how this completed booking was paid (post-redemption)."""
    r = await session.execute(
        text(
            """
            SELECT pi.sessions_remaining
            FROM pass_redemptions pr
            JOIN pass_instances pi ON pi.id = pr.pass_instance_id
            WHERE pr.booking_id = :bid
            LIMIT 1
            """
        ),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if row:
        rem = row[0]
        return BookingDeductionSnapshot(
            outcome="pass",
            pass_sessions_remaining=int(rem) if rem is not None else None,
        )

    r2 = await session.execute(
        text(
            """
            SELECT cbc.amount_cents, ci.amount_remaining_cents
            FROM certificate_booking_credits cbc
            JOIN certificate_instances ci ON ci.id = cbc.certificate_instance_id
            WHERE cbc.booking_id = :bid
            LIMIT 1
            """
        ),
        {"bid": booking_id},
    )
    row2 = r2.fetchone()
    if row2:
        amt, rem = row2[0], row2[1]
        return BookingDeductionSnapshot(
            outcome="cert",
            cert_amount_cents=int(amt) if amt is not None else None,
            cert_remaining_cents=int(rem) if rem is not None else None,
        )

    return BookingDeductionSnapshot(outcome="none")
