"""
Prorate subscription invoice amount using referral bonus-day balance (wallet).

Rule: up to ``period_days`` bonus days can cover the period; the trainer pays for the rest
of the period proportionally (same as list price × payable_days / period_days).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.referral_use_cases import get_referral_credit_balance


def prorate_subscription_amount_cents(total_cents: int, payable_period_days: int, invoice_period_days: int) -> int:
    """Return amount to charge in cents for ``payable_period_days`` of ``invoice_period_days`` at list ``total_cents``."""
    if total_cents <= 0 or invoice_period_days <= 0:
        return max(0, total_cents)
    if payable_period_days <= 0:
        return 0
    if payable_period_days >= invoice_period_days:
        return int(total_cents)
    d = Decimal(int(total_cents) * int(payable_period_days)) / Decimal(int(invoice_period_days))
    out = int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if out == 0 and payable_period_days > 0:
        return 1
    return out


async def compute_referral_invoice_discount(
    session: AsyncSession,
    trainer_id: int,
    *,
    total_cents: int,
    period_days: int,
) -> tuple[int, int, int]:
    """
    Returns (discounted_amount_cents, bonus_days_to_apply, list_price_cents).

    ``bonus_days_to_apply`` is capped by current referral balance and by ``period_days``.
    """
    list_price = int(total_cents)
    if list_price <= 0 or period_days <= 0:
        return list_price, 0, list_price
    balance = await get_referral_credit_balance(session, trainer_id)
    bonus_days = min(int(balance), int(period_days))
    payable_days = int(period_days) - bonus_days
    discounted = prorate_subscription_amount_cents(list_price, payable_days, int(period_days))
    return discounted, bonus_days, list_price
