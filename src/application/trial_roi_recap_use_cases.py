"""
Trial-end ROI recap: evidence-based value proof before the billing reminder.

The goal is credible directional proof, not audit-grade time tracking. We count only concrete
manual work the platform plausibly replaced: self-booking, reminders, confirmations, repeat
bookings, and pass/certificate accounting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import SUBSCRIPTION_STATUS_TRIAL


@dataclass(frozen=True, slots=True)
class TrialRoiRecap:
    """Trainer-facing proof of value accumulated during the current trial window."""

    trainer_id: int
    period_start: datetime
    period_end: datetime
    completed_sessions_count: int
    self_bookings_count: int
    self_confirmations_count: int
    repeat_bookings_count: int
    future_available_slots_count: int
    auto_reminders_sent_count: int
    pass_redemptions_count: int
    certificate_credits_count: int
    revenue_sessions_cents: int
    revenue_pass_sales_cents: int
    revenue_certificate_sales_cents: int

    @property
    def revenue_total_cents(self) -> int:
        return (
            self.revenue_sessions_cents
            + self.revenue_pass_sales_cents
            + self.revenue_certificate_sales_cents
        )

    @property
    def saved_minutes_raw(self) -> float:
        """Heuristic proxy for avoided manual coordination work."""
        return (
            self.self_bookings_count * 4
            + self.auto_reminders_sent_count * 1.5
            + self.self_confirmations_count * 1.5
            + self.repeat_bookings_count * 3
            + self.pass_redemptions_count * 1
            + self.certificate_credits_count * 1
        )

    @property
    def saved_minutes_display(self) -> int:
        """Round to believable 5-minute buckets; never pretend sub-minute precision."""
        raw = self.saved_minutes_raw
        if raw <= 0:
            return 0
        rounded = int(round(raw / 5.0) * 5)
        return max(5, rounded)


async def list_trial_roi_recap_due(
    session: AsyncSession,
    *,
    roi_days_ahead: int,
    final_reminder_days_ahead: int,
    limit: int = 50,
) -> list[dict]:
    """
    Current trial subscriptions eligible for the D-2 ROI recap.

    Window is strictly between the final trial loss-reminder (``final_reminder_days_ahead``,
    default D-1) and ``roi_days_ahead`` (default D-2). If the worker was offline and we are
    already inside the loss-reminder window, we skip the recap rather than stack two
    conversion messages on the same day.
    """
    now = datetime.now(timezone.utc)
    final_start = now + timedelta(days=max(1, int(final_reminder_days_ahead)))
    roi_end = now + timedelta(days=max(1, int(roi_days_ahead)))
    if roi_end <= final_start:
        return []

    r = await session.execute(
        text(
            """
            SELECT ts.id, ts.trainer_id, ts.started_at, ts.expires_at, t.telegram_id
            FROM trainer_subscriptions ts
            JOIN trainers t ON t.id = ts.trainer_id
            WHERE ts.status = :trial
              AND ts.expires_at > :final_start
              AND ts.expires_at <= :roi_end
              AND ts.trial_roi_recap_sent_at IS NULL
              AND t.telegram_id IS NOT NULL
            ORDER BY ts.expires_at ASC
            LIMIT :lim
            """
        ),
        {
            "trial": SUBSCRIPTION_STATUS_TRIAL,
            "final_start": final_start,
            "roi_end": roi_end,
            "lim": max(1, int(limit)),
        },
    )
    return [
        {
            "id": int(row[0]),
            "trainer_id": int(row[1]),
            "started_at": row[2],
            "expires_at": row[3],
            "trainer_telegram_id": int(row[4]),
        }
        for row in r.fetchall()
    ]


async def get_trial_roi_recap(
    session: AsyncSession,
    *,
    trainer_id: int,
    period_start: datetime,
    period_end: datetime,
) -> TrialRoiRecap:
    """Aggregate ROI proof for one trainer over the active trial period so far."""
    params = {"tid": trainer_id, "start": period_start, "end": period_end}

    r = await session.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (WHERE b.status = 'completed')::int AS completed_sessions,
              COUNT(*) FILTER (WHERE b.notified_at IS NOT NULL OR b.status = 'pending')::int AS self_bookings,
              COUNT(*) FILTER (
                WHERE b.notified_at IS NOT NULL
                  AND b.client_notified_trainer_booked_at IS NOT NULL
                  AND b.status IN ('confirmed', 'completed')
              )::int AS self_confirmations,
              COUNT(*) FILTER (
                WHERE EXISTS (
                  SELECT 1
                  FROM bookings prev
                  WHERE prev.trainer_id = b.trainer_id
                    AND prev.client_id = b.client_id
                    AND prev.id <> b.id
                    AND prev.created_at < b.created_at
                    AND prev.status IN ('completed', 'confirmed')
                )
              )::int AS repeat_bookings
            FROM bookings b
            WHERE b.trainer_id = :tid
              AND b.created_at >= :start
              AND b.created_at <= :end
              AND b.status NOT IN ('cancelled', 'declined', 'no_show', 'payment_dispute', 'trainer_removed')
            """
        ),
        params,
    )
    booking_row = r.fetchone() or (0, 0, 0, 0)

    r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM slots
            WHERE trainer_id = :tid
              AND status = 'available'
              AND slot_date >= CURRENT_DATE
              AND slot_date <= (CURRENT_DATE + INTERVAL '14 days')
            """
        ),
        {"tid": trainer_id},
    )
    future_available_slots_count = int(r.scalar() or 0)

    r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM reminders rem
            JOIN bookings b ON b.id = rem.booking_id
            WHERE b.trainer_id = :tid
              AND rem.status = 'sent'
              AND rem.sent_at >= :start
              AND rem.sent_at <= :end
            """
        ),
        params,
    )
    auto_reminders_sent_count = int(r.scalar() or 0)

    r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM pass_redemptions pr
            JOIN bookings b ON b.id = pr.booking_id
            WHERE b.trainer_id = :tid
              AND pr.redeemed_at >= :start
              AND pr.redeemed_at <= :end
            """
        ),
        params,
    )
    pass_redemptions_count = int(r.scalar() or 0)

    r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM certificate_booking_credits cbc
            JOIN bookings b ON b.id = cbc.booking_id
            WHERE b.trainer_id = :tid
              AND b.status = 'completed'
              AND b.created_at >= :start
              AND b.created_at <= :end
            """
        ),
        params,
    )
    certificate_credits_count = int(r.scalar() or 0)

    r = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(
                CASE WHEN pr.booking_id IS NOT NULL THEN 0
                     ELSE GREATEST(0, COALESCE(b.booking_price_cents, spv.price_cents, ts.price_cents, 0)
                                      - COALESCE(cbc.amount_cents, 0))
                END
            ), 0)::bigint
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            LEFT JOIN pass_redemptions pr ON pr.booking_id = b.id
            LEFT JOIN certificate_booking_credits cbc ON cbc.booking_id = b.id
            WHERE b.trainer_id = :tid
              AND b.status = 'completed'
              AND s.status IN ('available', 'booked')
              AND b.created_at >= :start
              AND b.created_at <= :end
            """
        ),
        params,
    )
    revenue_sessions_cents = int(r.scalar() or 0)

    r = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(tpp.price_cents), 0)::bigint
            FROM pass_instances pi
            JOIN trainer_pass_products tpp ON tpp.id = pi.pass_product_id
            WHERE tpp.trainer_id = :tid
              AND pi.status != 'cancelled'
              AND pi.source_certificate_instance_id IS NULL
              AND pi.issued_at >= :start
              AND pi.issued_at <= :end
            """
        ),
        params,
    )
    revenue_pass_sales_cents = int(r.scalar() or 0)

    r = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(ci.amount_cents), 0)::bigint
            FROM certificate_instances ci
            WHERE ci.trainer_id = :tid
              AND ci.status != 'cancelled'
              AND ci.issued_at >= :start
              AND ci.issued_at <= :end
            """
        ),
        params,
    )
    revenue_certificate_sales_cents = int(r.scalar() or 0)

    return TrialRoiRecap(
        trainer_id=trainer_id,
        period_start=period_start,
        period_end=period_end,
        completed_sessions_count=int(booking_row[0] or 0),
        self_bookings_count=int(booking_row[1] or 0),
        self_confirmations_count=int(booking_row[2] or 0),
        repeat_bookings_count=int(booking_row[3] or 0),
        future_available_slots_count=future_available_slots_count,
        auto_reminders_sent_count=auto_reminders_sent_count,
        pass_redemptions_count=pass_redemptions_count,
        certificate_credits_count=certificate_credits_count,
        revenue_sessions_cents=revenue_sessions_cents,
        revenue_pass_sales_cents=revenue_pass_sales_cents,
        revenue_certificate_sales_cents=revenue_certificate_sales_cents,
    )


async def mark_trial_roi_recap_sent(session: AsyncSession, subscription_id: int) -> None:
    """Idempotency marker: one ROI recap per trial subscription."""
    await session.execute(
        text(
            """
            UPDATE trainer_subscriptions
            SET trial_roi_recap_sent_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """
        ),
        {"id": subscription_id},
    )
    await session.commit()


__all__ = [
    "TrialRoiRecap",
    "get_trial_roi_recap",
    "list_trial_roi_recap_due",
    "mark_trial_roi_recap_sent",
]
