"""Pure tests for post-booking profile enrichment nudges — no DB, no Telegram."""
from __future__ import annotations

from src.application.trainer_profile_enrichment_use_cases import (
    _pick_due_step,
    render_profile_enrichment_nudge_text,
)
from src.infrastructure.db.models import (
    PROFILE_NUDGE_STEP_P1,
    PROFILE_NUDGE_STEP_P8,
    PROFILE_NUDGE_STEP_P21,
)


def test_before_first_day_yields_none() -> None:
    assert _pick_due_step(days_since_first_booking=0, already_sent=frozenset()) is None


def test_day_one_picks_playful_opener() -> None:
    assert _pick_due_step(days_since_first_booking=1, already_sent=frozenset()) == (
        PROFILE_NUDGE_STEP_P1,
        1,
    )


def test_week_later_picks_p8_if_p1_already_sent() -> None:
    assert _pick_due_step(
        days_since_first_booking=8, already_sent=frozenset({PROFILE_NUDGE_STEP_P1})
    ) == (PROFILE_NUDGE_STEP_P8, 8)


def test_late_tick_fast_forwards_to_last_step() -> None:
    assert _pick_due_step(days_since_first_booking=40, already_sent=frozenset()) == (
        PROFILE_NUDGE_STEP_P21,
        21,
    )


def test_series_exhausted_is_silent() -> None:
    assert (
        _pick_due_step(
            days_since_first_booking=40,
            already_sent=frozenset(
                {PROFILE_NUDGE_STEP_P1, PROFILE_NUDGE_STEP_P8, PROFILE_NUDGE_STEP_P21}
            ),
        )
        is None
    )


def test_copy_says_what_to_do_without_urgency() -> None:
    t1 = render_profile_enrichment_nudge_text(PROFILE_NUDGE_STEP_P1)
    t8 = render_profile_enrichment_nudge_text(PROFILE_NUDGE_STEP_P8)
    t21 = render_profile_enrichment_nudge_text(PROFILE_NUDGE_STEP_P21)
    blob = (t1 + t8 + t21).lower()
    assert "цену занятия" in t1.lower()
    assert "профил" in blob
    assert "тариф" in blob
    assert "не входит" in blob
    for forbidden in ("заполни", "срочно", "добить", "обязательн", "почём", "почем"):
        assert forbidden not in blob


def test_nudge_has_open_profile_button_label() -> None:
    from src.bot import messages as msg

    assert msg.TRAINER_PROFILE_ENRICH_NUDGE_BTN == "Открыть профиль"
