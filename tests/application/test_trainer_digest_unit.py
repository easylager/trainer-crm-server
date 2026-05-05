"""Pure unit tests for the trainer digest scheduler + gap computation.

No DB involved. DB-backed aggregators live in ``test_trainer_digest_integration.py``.
"""
from datetime import time

from src.application.trainer_digest_use_cases import (
    _compute_gaps,
    resolve_digest_send_time,
    resolve_weekly_digest_send_time,
)


def _sess(start: time, end: time) -> dict:
    return {"start_time": start, "end_time": end}


def test_gaps_empty_when_no_sessions() -> None:
    assert _compute_gaps([], min_minutes=120) == []


def test_gaps_empty_when_single_session() -> None:
    assert _compute_gaps([_sess(time(9, 0), time(10, 0))], min_minutes=120) == []


def test_gaps_below_threshold_skipped() -> None:
    sessions = [
        _sess(time(9, 0), time(10, 0)),
        _sess(time(10, 30), time(11, 30)),
    ]
    assert _compute_gaps(sessions, min_minutes=120) == []


def test_gaps_exactly_at_threshold_surfaces() -> None:
    sessions = [
        _sess(time(9, 0), time(10, 0)),
        _sess(time(12, 0), time(13, 0)),
    ]
    gaps = _compute_gaps(sessions, min_minutes=120)
    assert len(gaps) == 1
    assert gaps[0]["duration_minutes"] == 120
    assert gaps[0]["from_time"] == time(10, 0)
    assert gaps[0]["to_time"] == time(12, 0)


def test_gaps_multiple_surfaces_all_matching() -> None:
    sessions = [
        _sess(time(9, 0), time(10, 0)),
        _sess(time(14, 0), time(15, 0)),
        _sess(time(18, 0), time(19, 0)),
    ]
    gaps = _compute_gaps(sessions, min_minutes=120)
    assert [g["duration_minutes"] for g in gaps] == [240, 180]


def test_resolve_explicit_setting_always_wins() -> None:
    assert (
        resolve_digest_send_time(
            digest_send_time=time(7, 30),
            first_session_start=time(9, 0),
            push_window_start_hour=8,
            push_window_end_hour=22,
        )
        == time(7, 30)
    )


def test_resolve_explicit_setting_honored_even_inside_quiet_hours() -> None:
    """Opt-in ritual beats default quiet-hours window — trainer's own choice wins."""
    assert (
        resolve_digest_send_time(
            digest_send_time=time(5, 0),
            first_session_start=time(9, 0),
            push_window_start_hour=8,
            push_window_end_hour=22,
        )
        == time(5, 0)
    )


def test_resolve_auto_morning_default_before_typical_first_session() -> None:
    """Раньше было «за час до»; теперь авто — утренний слот 8:00, если тренировка не раньше."""
    assert (
        resolve_digest_send_time(
            digest_send_time=None,
            first_session_start=time(9, 0),
            push_window_start_hour=8,
            push_window_end_hour=22,
        )
        == time(8, 0)
    )


def test_resolve_auto_evening_session_stays_morning_not_one_hour_before() -> None:
    """Запись на вечер не переносит дайджест на «за час до» (избегаем «Доброе утро» в 16:00)."""
    assert (
        resolve_digest_send_time(
            digest_send_time=None,
            first_session_start=time(17, 0),
            push_window_start_hour=8,
            push_window_end_hour=22,
        )
        == time(8, 0)
    )


def test_resolve_clamps_to_push_window_start() -> None:
    """Auto-compute cannot violate push window — clamps to lower bound."""
    assert (
        resolve_digest_send_time(
            digest_send_time=None,
            first_session_start=time(8, 30),
            push_window_start_hour=8,
            push_window_end_hour=22,
        )
        == time(8, 0)
    )


def test_resolve_auto_no_session_uses_default_morning() -> None:
    """Без тренировок — всё равно утренний слот (для lite-дайджеста с заявками)."""
    assert (
        resolve_digest_send_time(
            digest_send_time=None,
            first_session_start=None,
            push_window_start_hour=8,
            push_window_end_hour=22,
        )
        == time(8, 0)
    )


def test_resolve_late_first_session_still_morning_in_window() -> None:
    """Поздняя первая тренировка не тянет авто-время к вечеру — остаётся утро."""
    assert (
        resolve_digest_send_time(
            digest_send_time=None,
            first_session_start=time(23, 0),
            push_window_start_hour=8,
            push_window_end_hour=22,
        )
        == time(8, 0)
    )


def test_resolve_respects_trainer_widened_window() -> None:
    """Trainer pushed start hour to 6 → auto can fire at 6:00."""
    assert (
        resolve_digest_send_time(
            digest_send_time=None,
            first_session_start=time(7, 0),
            push_window_start_hour=6,
            push_window_end_hour=22,
        )
        == time(6, 0)
    )


def test_weekly_evening_default_in_standard_push_window() -> None:
    assert (
        resolve_weekly_digest_send_time(
            push_window_start_hour=8,
            push_window_end_hour=22,
        )
        == time(20, 0)
    )


def test_weekly_moves_earlier_when_window_ends_before_20() -> None:
    """If end_hour is exclusive at 20:00, 20:00 is out — drop to 19:00."""
    assert (
        resolve_weekly_digest_send_time(
            push_window_start_hour=8,
            push_window_end_hour=20,
        )
        == time(19, 0)
    )


def test_weekly_clamps_not_before_window_start_if_late_start() -> None:
    """Window starts after default evening → schedule at lower bound."""
    assert (
        resolve_weekly_digest_send_time(
            push_window_start_hour=21,
            push_window_end_hour=24,
        )
        == time(21, 0)
    )


def test_resolve_custom_lead_only_pulls_earlier_than_default_morning() -> None:
    """lead_minutes влияет только если первая тренировка раньше 08:00 по расчёту."""
    assert (
        resolve_digest_send_time(
            digest_send_time=None,
            first_session_start=time(10, 0),
            push_window_start_hour=8,
            push_window_end_hour=22,
            lead_minutes=30,
        )
        == time(8, 0)
    )
    assert (
        resolve_digest_send_time(
            digest_send_time=None,
            first_session_start=time(7, 0),
            push_window_start_hour=6,
            push_window_end_hour=22,
            lead_minutes=60,
        )
        == time(6, 0)
    )
