"""Public catalog view-transition name helpers."""

from src.shared.public_view_transitions import (
    WHEN_STRIP_VT_NAME,
    session_time_vt_name,
    session_time_vt_style,
)


def test_session_time_vt_name_uses_session_id() -> None:
    assert session_time_vt_name(24633) == "glide-s-24633"


def test_session_time_vt_style_quotes_name() -> None:
    assert 'view-transition-name: glide-s-7' in session_time_vt_style(7)


def test_when_strip_constant() -> None:
    assert WHEN_STRIP_VT_NAME == "glide-when-strip"
