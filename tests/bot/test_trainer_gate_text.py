"""Trainer bot gate / first-link onboarding copy."""

from src.application.trainer_access_state import TrainerAccessState
from src.bot import messages as msg
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.handlers.trainer_handlers import (
    _first_run_caption,
    _send_first_run_offer,
    _trial_welcome_labels,
)
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
    assert "ссылк" in low and "ученик" in low
    assert "заполнять ничего не нужно" not in low, "за кнопкой три шага — не обещаем пустоту"
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


def test_first_run_caption_greets_by_telegram_name_safely() -> None:
    """TASK-312: имя из Telegram — первой строкой; HTML в имени не ломает разметку подписи."""
    assert _first_run_caption("Анна").startswith("Анна, здравствуйте.\n\n")
    assert _first_run_caption("<b>X</b>").startswith("&lt;b&gt;X&lt;/b&gt;, здравствуйте.")
    assert _first_run_caption(None) == msg.TRAINER_AFTER_LINK_HERO
    assert _first_run_caption("   ") == msg.TRAINER_AFTER_LINK_HERO


@pytest.mark.asyncio
async def test_first_run_offer_is_a_photo_with_one_button() -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(first_name="Анна"), answer_photo=AsyncMock(), answer=AsyncMock()
    )
    kb = object()
    await _send_first_run_offer(message, kb)
    message.answer_photo.assert_awaited_once()
    kwargs = message.answer_photo.await_args.kwargs
    assert kwargs["reply_markup"] is kb
    assert kwargs["caption"].startswith("Анна, здравствуйте.")
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_run_offer_falls_back_to_text_when_photo_fails() -> None:
    """Картинка — объяснение, а не условие: без неё тренер получает тот же текст и кнопку."""
    message = SimpleNamespace(
        from_user=SimpleNamespace(first_name="Анна"),
        answer_photo=AsyncMock(side_effect=RuntimeError("telegram said no")),
        answer=AsyncMock(),
    )
    kb = object()
    await _send_first_run_offer(message, kb)
    message.answer.assert_awaited_once()
    assert message.answer.await_args.kwargs["reply_markup"] is kb
    assert message.answer.await_args.args[0].startswith("Анна, здравствуйте.")
