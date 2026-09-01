"""Pure tests for the onboarding-reactivation scheduler — stage picker + step picker. No DB, no Telegram."""
from __future__ import annotations

import pytest

from src.application.trainer_onboarding_recovery_use_cases import (
    STAGE_EMPTY_FORM,
    STAGE_MISSING_FIELD,
    STAGE_NOT_SUBMITTED,
    STAGE_NO_BOOKING,
    STAGE_REJECTED_RESUBMIT,
    DueOnboardingNudge,
    _pick_due_step,
    determine_onboarding_stage,
)
from src.infrastructure.db.models import (
    ONBOARDING_NUDGE_STEP_D1,
    ONBOARDING_NUDGE_STEP_D3,
    ONBOARDING_NUDGE_STEP_D7,
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_PROFILE,
)


class TestDetermineOnboardingStage:
    def test_empty_form_when_tt_minimal_incomplete(self):
        assert (
            determine_onboarding_stage(
                trainer_status=TRAINER_STATUS_PENDING_PROFILE,
                tt_minimal_complete=False,
                profile_complete=False,
                moderation_submitted=False,
                has_moderation_feedback=False,
                has_any_booking=False,
            )
            == STAGE_EMPTY_FORM
        )

    def test_missing_field_when_tt_minimal_done_but_submission_incomplete(self):
        assert (
            determine_onboarding_stage(
                trainer_status=TRAINER_STATUS_PENDING_PROFILE,
                tt_minimal_complete=True,
                profile_complete=False,
                moderation_submitted=False,
                has_moderation_feedback=False,
                has_any_booking=False,
            )
            == STAGE_MISSING_FIELD
        )

    def test_rejected_resubmit_when_feedback_present_and_not_resubmitted(self):
        assert (
            determine_onboarding_stage(
                trainer_status=TRAINER_STATUS_PENDING_PROFILE,
                tt_minimal_complete=True,
                profile_complete=True,
                moderation_submitted=False,
                has_moderation_feedback=True,
                has_any_booking=False,
            )
            == STAGE_REJECTED_RESUBMIT
        )

    def test_not_submitted_when_ready_but_not_sent(self):
        assert (
            determine_onboarding_stage(
                trainer_status=TRAINER_STATUS_PENDING_PROFILE,
                tt_minimal_complete=True,
                profile_complete=True,
                moderation_submitted=False,
                has_moderation_feedback=False,
                has_any_booking=False,
            )
            == STAGE_NOT_SUBMITTED
        )

    def test_none_when_pending_profile_fully_submitted(self):
        # Ready + submitted + no feedback: waiting on admin review, nothing actionable for trainer.
        assert (
            determine_onboarding_stage(
                trainer_status=TRAINER_STATUS_PENDING_PROFILE,
                tt_minimal_complete=True,
                profile_complete=True,
                moderation_submitted=True,
                has_moderation_feedback=False,
                has_any_booking=False,
            )
            is None
        )

    def test_no_booking_when_active_with_zero_bookings(self):
        assert (
            determine_onboarding_stage(
                trainer_status=TRAINER_STATUS_ACTIVE,
                tt_minimal_complete=True,
                profile_complete=True,
                moderation_submitted=True,
                has_moderation_feedback=False,
                has_any_booking=False,
            )
            == STAGE_NO_BOOKING
        )

    def test_none_when_pending_profile_already_has_a_booking(self):
        """Онбординг v2: запись есть, анкета пустая — не долбим «заполни поля»."""
        assert (
            determine_onboarding_stage(
                trainer_status=TRAINER_STATUS_PENDING_PROFILE,
                tt_minimal_complete=True,
                profile_complete=False,
                moderation_submitted=False,
                has_moderation_feedback=False,
                has_any_booking=True,
            )
            is None
        )

    def test_none_when_active_with_a_booking(self):
        assert (
            determine_onboarding_stage(
                trainer_status=TRAINER_STATUS_ACTIVE,
                tt_minimal_complete=True,
                profile_complete=True,
                moderation_submitted=True,
                has_moderation_feedback=False,
                has_any_booking=True,
            )
            is None
        )

    def test_none_for_status_outside_segment(self):
        # e.g. deactivated — not part of this segment at all.
        assert (
            determine_onboarding_stage(
                trainer_status=TRAINER_STATUS_DEACTIVATED,
                tt_minimal_complete=False,
                profile_complete=False,
                moderation_submitted=False,
                has_moderation_feedback=False,
                has_any_booking=False,
            )
            is None
        )


class TestPickDueStep:
    def test_fresh_start_picks_d1(self):
        assert _pick_due_step(days_since_start=1, already_sent=frozenset()) == (
            ONBOARDING_NUDGE_STEP_D1,
            1,
        )

    def test_before_d1_window_yields_none(self):
        assert _pick_due_step(days_since_start=0, already_sent=frozenset()) is None

    def test_after_d1_sent_d3_due_at_3_days(self):
        assert _pick_due_step(
            days_since_start=3, already_sent=frozenset({ONBOARDING_NUDGE_STEP_D1})
        ) == (ONBOARDING_NUDGE_STEP_D3, 3)

    def test_late_re_enable_skips_to_d7(self):
        assert _pick_due_step(days_since_start=20, already_sent=frozenset()) == (
            ONBOARDING_NUDGE_STEP_D7,
            7,
        )

    def test_series_exhausted_returns_none(self):
        assert (
            _pick_due_step(
                days_since_start=30,
                already_sent=frozenset(
                    {ONBOARDING_NUDGE_STEP_D1, ONBOARDING_NUDGE_STEP_D3, ONBOARDING_NUDGE_STEP_D7}
                ),
            )
            is None
        )

    def test_skips_lower_offset_when_higher_unfired(self):
        assert _pick_due_step(days_since_start=7, already_sent=frozenset()) == (
            ONBOARDING_NUDGE_STEP_D7,
            7,
        )


def _nudge(*, step: str, stage: str, missing: tuple[str, ...] = ()) -> DueOnboardingNudge:
    return DueOnboardingNudge(
        trainer_id=1,
        trainer_telegram_id=123,
        step=step,
        days_offset=1,
        days_since_start=1,
        stage=stage,
        missing_labels_ru=missing,
    )


class TestRenderOnboardingNudgeText:
    """Message rendering: step intro + stage body + trial urgency suffix (TASK-011 AC-002/AC-004)."""

    def test_empty_form_stage_renders_body(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D1, stage=STAGE_EMPTY_FORM),
            trial_days_remaining=None,
        )
        assert "Рады, что вы заглянули" in text
        assert "расписание" in text.lower()
        assert "Обзор" in text
        assert "заполни" not in text.lower()

    def test_empty_form_d3_uses_warming_intro_not_homework(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D3, stage=STAGE_EMPTY_FORM),
            trial_days_remaining=None,
        )
        assert "кабинет уже ждёт" in text.lower()
        assert "регистрац" not in text.lower()

    def test_missing_field_stage_names_concrete_labels(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(
                step=ONBOARDING_NUDGE_STEP_D3,
                stage=STAGE_MISSING_FIELD,
                missing=("город", "услуга"),
            ),
            trial_days_remaining=None,
        )
        assert "город" in text
        assert "услуга" in text

    def test_missing_photo_only_is_playful(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(
                step=ONBOARDING_NUDGE_STEP_D3,
                stage=STAGE_MISSING_FIELD,
                missing=("фотография профиля",),
            ),
            trial_days_remaining=None,
        )
        assert "Улыбочку" in text
        assert "фото" in text.lower()
        assert "заполни" not in text.lower()

    def test_missing_field_falls_back_when_labels_empty(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D3, stage=STAGE_MISSING_FIELD, missing=()),
            trial_days_remaining=None,
        )
        assert "оставшиеся поля анкеты" in text

    def test_no_trial_suffix_when_days_remaining_none(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D1, stage=STAGE_EMPTY_FORM),
            trial_days_remaining=None,
        )
        assert "Пробный период" not in text

    def test_no_trial_suffix_when_above_urgency_threshold(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D1, stage=STAGE_EMPTY_FORM),
            trial_days_remaining=10,
        )
        assert "Пробный период" not in text

    def test_trial_suffix_with_days_left_at_threshold(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D7, stage=STAGE_NO_BOOKING),
            trial_days_remaining=2,
        )
        assert "ещё 2 дн." in text

    def test_trial_suffix_last_day(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D7, stage=STAGE_NO_BOOKING),
            trial_days_remaining=0,
        )
        assert "заканчивается сегодня" in text

    def test_rejected_resubmit_stage_renders(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D3, stage=STAGE_REJECTED_RESUBMIT),
            trial_days_remaining=None,
        )
        assert "замечания" in text.lower()

    def test_not_submitted_stage_renders(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D3, stage=STAGE_NOT_SUBMITTED),
            trial_days_remaining=None,
        )
        assert "отправить" in text.lower()

    def test_no_booking_stage_renders(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        text = _render_onboarding_nudge_text(
            _nudge(step=ONBOARDING_NUDGE_STEP_D7, stage=STAGE_NO_BOOKING),
            trial_days_remaining=None,
        )
        assert "запись" in text.lower()

    def test_unknown_step_raises(self):
        from src.bot.notification_loops import _render_onboarding_nudge_text

        with pytest.raises(ValueError):
            _render_onboarding_nudge_text(
                _nudge(step="d999", stage=STAGE_EMPTY_FORM), trial_days_remaining=None
            )
