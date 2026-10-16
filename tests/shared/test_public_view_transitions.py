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


def test_place_vt_name_is_shared_by_card_and_hero() -> None:
    from src.shared.public_view_transitions import place_vt_name, place_vt_style

    assert place_vt_name("Minsk-Arena") == "glide-place-minsk-arena"
    assert 'view-transition-name: glide-place-minsk-arena' in place_vt_style("minsk-arena")
    assert place_vt_style("") == ""
    from src.shared.public_view_transitions import place_vt_attr

    assert place_vt_attr("minsk-arena") == ' data-place-vt="glide-place-minsk-arena"'
    assert "view-transition-name" not in place_vt_attr("minsk-arena")
