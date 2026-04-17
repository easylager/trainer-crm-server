"""Settings: resolved trainer subscription checkout mode (sandbox / bepaid / invoice)."""

from src.shared.config import Settings


def test_resolved_mode_explicit_invoice() -> None:
    s = Settings(
        payment_sandbox=False,
        bepaid_shop_id="shop",
        bepaid_secret_key="sec",
        trainer_subscription_checkout_mode="invoice",
    )
    assert s.resolved_trainer_subscription_checkout_mode() == "invoice"


def test_resolved_mode_auto_prefers_bepaid_when_credentials() -> None:
    s = Settings(
        payment_sandbox=False,
        bepaid_shop_id="shop",
        bepaid_secret_key="sec",
        trainer_subscription_checkout_mode="auto",
    )
    assert s.resolved_trainer_subscription_checkout_mode() == "bepaid"


def test_resolved_mode_auto_invoice_without_bepaid() -> None:
    s = Settings(
        payment_sandbox=False,
        bepaid_shop_id=None,
        bepaid_secret_key=None,
        trainer_subscription_checkout_mode="auto",
    )
    assert s.resolved_trainer_subscription_checkout_mode() == "invoice"


def test_resolved_mode_auto_invoice_when_bepaid_shop_blank() -> None:
    s = Settings(
        payment_sandbox=False,
        bepaid_shop_id="   ",
        bepaid_secret_key="x",
        trainer_subscription_checkout_mode="auto",
    )
    assert s.resolved_trainer_subscription_checkout_mode() == "invoice"


def test_resolved_mode_sandbox_when_flag_on() -> None:
    s = Settings(
        payment_sandbox=True,
        trainer_subscription_checkout_mode="auto",
    )
    assert s.resolved_trainer_subscription_checkout_mode() == "sandbox"
