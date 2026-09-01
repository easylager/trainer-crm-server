"""Trainer bot gate / first-link onboarding copy."""

from src.application.trainer_access_state import TrainerAccessState
from src.bot import messages as msg
from src.bot.handlers.trainer_handlers import _trial_welcome_labels
from src.bot.trainer_gate_text import trainer_first_link_onboarding_html


def test_after_link_hero_sells_the_action_not_the_product() -> None:
    """
    Onboarding v2 copy rule: the first message promises one outcome and asks for one tap.
    No feature list, no «CRM», no anketa, no trial — those all switch the reader into
    evaluation mode when we need them in working mode.
    """
    hero = msg.TRAINER_AFTER_LINK_HERO
    low = hero.lower()
    for forbidden in ("crm", "анкет", "провер", "пробный период", "тариф", "первые шаги"):
        assert forbidden not in low, f"hero must not mention «{forbidden}»"
    assert "ссылка" in low and "ученик" in low
    assert len(hero) < 280


def test_new_trainer_after_link_gets_the_hero() -> None:
    """A freshly linked trainer with an empty profile sees the offer, never a gate."""
    assert trainer_first_link_onboarding_html(TrainerAccessState.ACTIVE, None) == msg.TRAINER_AFTER_LINK_HERO


def test_deactivated_after_link_is_told_plainly() -> None:
    assert (
        trainer_first_link_onboarding_html(TrainerAccessState.DEACTIVATED, None)
        == msg.TRAINER_AFTER_LINK_STEP_DEACTIVATED
    )


def test_trial_welcome_labels_requires_active_trial_tier() -> None:
    assert _trial_welcome_labels({"is_active": False, "is_trial": True, "effective_tier": "crm"}) is None
    assert _trial_welcome_labels({"is_active": True, "is_trial": False, "effective_tier": "crm"}) is None
    assert _trial_welcome_labels({"is_active": True, "is_trial": True, "effective_tier": "none"}) is None
    labels = _trial_welcome_labels(
        {
            "is_active": True,
            "is_trial": True,
            "effective_tier": "crm",
            "tier_name_ru": "Полный доступ",
            "expires_at": "2026-09-14T12:00:00+00:00",
        }
    )
    assert labels == ("Полный доступ", "14.09.2026")
