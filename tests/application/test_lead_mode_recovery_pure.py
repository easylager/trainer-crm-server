"""Pure tests for the recovery scheduler step picker — no DB, no Telegram."""
from __future__ import annotations

import pytest

from src.application.lead_mode_recovery_use_cases import _pick_due_step
from src.infrastructure.db.models import (
    RECOVERY_STEP_D0,
    RECOVERY_STEP_D3,
    RECOVERY_STEP_D14,
    RECOVERY_STEP_D30,
)


class TestPickDueStep:
    """`_pick_due_step` is the heart of the schedule — it must be both pure and predictable."""

    def test_fresh_lead_mode_picks_d0(self):
        assert _pick_due_step(days_in_lead_mode=0, already_sent=frozenset()) == (
            RECOVERY_STEP_D0,
            0,
        )

    def test_after_d0_then_d3_due(self):
        assert _pick_due_step(
            days_in_lead_mode=4, already_sent=frozenset({RECOVERY_STEP_D0})
        ) == (RECOVERY_STEP_D3, 3)

    def test_after_d0_d3_then_d14_due(self):
        assert _pick_due_step(
            days_in_lead_mode=15,
            already_sent=frozenset({RECOVERY_STEP_D0, RECOVERY_STEP_D3}),
        ) == (RECOVERY_STEP_D14, 14)

    def test_all_offsets_elapsed_picks_largest_unfired(self):
        # Late re-enable: 40 days passed, nothing sent — fast-forward to D+30.
        assert _pick_due_step(days_in_lead_mode=40, already_sent=frozenset()) == (
            RECOVERY_STEP_D30,
            30,
        )

    def test_series_exhausted_returns_none(self):
        assert (
            _pick_due_step(
                days_in_lead_mode=100,
                already_sent=frozenset(
                    {
                        RECOVERY_STEP_D0,
                        RECOVERY_STEP_D3,
                        RECOVERY_STEP_D14,
                        RECOVERY_STEP_D30,
                    }
                ),
            )
            is None
        )

    def test_no_steps_due_yet_returns_none(self):
        # Hypothetical: 0 days, but D+0 was already sent — next firing is at day 3.
        assert (
            _pick_due_step(
                days_in_lead_mode=0, already_sent=frozenset({RECOVERY_STEP_D0})
            )
            is None
        )

    def test_d3_window_with_d0_sent(self):
        assert _pick_due_step(
            days_in_lead_mode=3, already_sent=frozenset({RECOVERY_STEP_D0})
        ) == (RECOVERY_STEP_D3, 3)

    def test_skips_zero_offset_steps_when_higher_unfired(self):
        # D+0 not sent, days=20 → still picks D+14, not D+0 (largest unfired wins).
        assert _pick_due_step(days_in_lead_mode=20, already_sent=frozenset()) == (
            RECOVERY_STEP_D14,
            14,
        )

    def test_d30_after_d14_at_30_days(self):
        assert _pick_due_step(
            days_in_lead_mode=30,
            already_sent=frozenset(
                {RECOVERY_STEP_D0, RECOVERY_STEP_D3, RECOVERY_STEP_D14}
            ),
        ) == (RECOVERY_STEP_D30, 30)


class TestRecoverySignalsLine:
    """Loss framing builder — must be honest with zero-demand cases."""

    def test_both_views_and_clicks(self):
        from src.bot.notification_loops import _render_recovery_signals_line

        line = _render_recovery_signals_line(views=12, clicks=3)
        assert "12" in line
        assert "3" in line
        assert "Telegram" in line

    def test_views_only(self):
        from src.bot.notification_loops import _render_recovery_signals_line

        line = _render_recovery_signals_line(views=7, clicks=0)
        assert "7" in line
        assert "Telegram" not in line

    def test_no_demand_returns_empty(self):
        from src.bot.notification_loops import _render_recovery_signals_line

        # Honest framing: don't fabricate "0 просмотров" — just omit the sentence.
        assert _render_recovery_signals_line(views=0, clicks=0) == ""

    def test_clicks_without_views_falls_back_to_empty(self):
        # Edge case: clicks-only is unusual (you'd expect a view first), so we treat as no-demand.
        from src.bot.notification_loops import _render_recovery_signals_line

        assert _render_recovery_signals_line(views=0, clicks=2) == ""
