"""Settings: resolved trainer subscription checkout mode (sandbox / invoice)."""

import pytest

from src.shared.config import Settings


def test_resolved_mode_explicit_invoice() -> None:
    s = Settings(payment_sandbox=False, trainer_subscription_checkout_mode="invoice")
    assert s.resolved_trainer_subscription_checkout_mode() == "invoice"


def test_resolved_mode_auto_invoice_when_not_sandbox() -> None:
    s = Settings(payment_sandbox=False, trainer_subscription_checkout_mode="auto")
    assert s.resolved_trainer_subscription_checkout_mode() == "invoice"


def test_resolved_mode_sandbox_when_flag_on() -> None:
    s = Settings(payment_sandbox=True, trainer_subscription_checkout_mode="auto")
    assert s.resolved_trainer_subscription_checkout_mode() == "sandbox"


@pytest.mark.parametrize("legacy", ["bepaid", "BePaid", "unknown"])
def test_removed_or_unknown_mode_falls_back_to_auto(legacy: str) -> None:
    """The bePaid mode no longer exists; an old env value must not break checkout."""
    s = Settings(payment_sandbox=False, trainer_subscription_checkout_mode=legacy)
    assert s.resolved_trainer_subscription_checkout_mode() == "invoice"
