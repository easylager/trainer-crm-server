"""Public catalog view-transition name helpers."""

from src.shared.public_view_transitions import (
    WHEN_STRIP_VT_NAME,
    session_time_vt_name,
    session_time_vt_style,
)


def test_session_time_vt_name_stable_for_arena_and_clock() -> None:
    assert session_time_vt_name(42, "9:30") == "glide-s-42-t930"
    assert session_time_vt_name(42, "09:30") == "glide-s-42-t0930"


def test_session_time_vt_style_quotes_name() -> None:
    assert 'view-transition-name: glide-s-7-t1200' in session_time_vt_style(7, "12:00")


def test_when_strip_constant() -> None:
    assert WHEN_STRIP_VT_NAME == "glide-when-strip"
