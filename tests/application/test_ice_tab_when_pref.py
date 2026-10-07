"""Ice tab «Когда» preference in client_sessions.payload."""

from src.application.client_session_use_cases import (
    ice_tab_when_from_session_row,
    normalize_ice_tab_when_pref,
)


def test_normalize_auto_to_any() -> None:
    assert normalize_ice_tab_when_pref("auto") == ("any", "")


def test_normalize_day_requires_iso() -> None:
    assert normalize_ice_tab_when_pref("day", "2030-06-15") == ("day", "2030-06-15")
    assert normalize_ice_tab_when_pref("day", "nope") == ("any", "")


def test_ice_tab_when_from_session_row() -> None:
    row = {"payload": {"ice_tab_when": "tomorrow", "ice_tab_when_day": ""}}
    assert ice_tab_when_from_session_row(row) == {"when": "tomorrow", "when_day": ""}
