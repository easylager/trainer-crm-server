"""Unit tests for referral wallet proration on subscription invoices."""

from __future__ import annotations

import pytest

from src.application.referral_subscription_discount import prorate_subscription_amount_cents


@pytest.mark.parametrize(
    "total,payable,days,expected",
    [
        (3000, 15, 30, 1500),
        (3000, 30, 30, 3000),
        (3000, 0, 30, 0),
        (100, 1, 30, 3),
        (0, 10, 30, 0),
        (2, 1, 100, 1),  # rounds to 0 → minimum 1 kopek when still payable
    ],
)
def test_prorate_subscription_amount_cents(total: int, payable: int, days: int, expected: int) -> None:
    assert prorate_subscription_amount_cents(total, payable, days) == expected
