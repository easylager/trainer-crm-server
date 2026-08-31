"""Trainer bot gate / first-link onboarding copy."""

from src.application.trainer_access_state import TrainerAccessState
from src.bot import messages as msg
from src.bot.handlers.trainer_handlers import _trial_welcome_labels
from src.bot.trainer_gate_text import trainer_first_link_onboarding_html


def test_after_link_hero_is_short_and_matches_landing_promise() -> None:
    hero = msg.TRAINER_AFTER_LINK_HERO
    assert "Платформа, которую строим вместе" not in hero
    assert "CRM для тренера на льду" in hero
    assert "пробный период" not in hero.lower()
    assert len(hero) < 280


def test_blocked_profile_onboarding_is_hero_only() -> None:
    html = trainer_first_link_onboarding_html(TrainerAccessState.BLOCKED_PROFILE, None)
    assert html == msg.TRAINER_AFTER_LINK_HERO


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
