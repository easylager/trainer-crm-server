"""Тексты и строки картинки для шеринга места (invite vs расписание)."""

from datetime import date, datetime, timezone

from src.application.client_share_message import share_body_for_native_share_dialog
from src.application.place_card_image import card_lines
from src.application.place_page import compose_place_share_message, share_payload


def _ice_view(**focus: object) -> dict:
    view = {
        "card": {
            "venue_type": "ice",
            "name": "Ледовый дворец",
            "city_name": "Минск",
            "district": "Фрунзенский район",
            "address": "ул. Притыцкого, 27",
        },
        "today": date(2026, 10, 10),
        "now": datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
        "session_count": 1,
    }
    if focus:
        view["focus"] = focus
    return view


def test_invite_share_body_is_only_the_hook() -> None:
    view = _ice_view(
        id=1,
        kind="public_skate",
        local_date="2026-10-10",
        starts_at_local="20:15:00",
        price_adult_minor=1000,
        currency_code="BYN",
    )
    url = "https://glide.example/p/minsk/ldk?s=1&i=1"
    payload = share_payload(view, page_url=url, invite=True)
    assert payload["share_body"] == "Погнали кататься?"
    assert share_body_for_native_share_dialog(payload["share_text"], url) == "Погнали кататься?"


def test_invite_card_lines_show_session_kind() -> None:
    mk = card_lines(
        _ice_view(
            id=1,
            kind="public_skate",
            local_date="2026-10-10",
            starts_at_local="20:15:00",
            price_adult_minor=1000,
            currency_code="BYN",
        ),
        invite=True,
    )
    assert mk["kind"] == "Массовое катание"

    ohm = card_lines(
        _ice_view(
            id=2,
            kind="hockey_practice",
            local_date="2026-10-12",
            starts_at_local="13:00:00",
            price_adult_minor=1400,
            currency_code="BYN",
        ),
        invite=True,
    )
    assert "ОХМ" in ohm["kind"]


def test_schedule_share_still_lists_facts() -> None:
    view = _ice_view(
        id=1,
        kind="public_skate",
        local_date="2026-10-10",
        starts_at_local="20:15:00",
        price_adult_minor=1000,
        currency_code="BYN",
    )
    text = compose_place_share_message(view, page_url="https://x/p", invite=False)
    assert "массовое катание" in text
    assert "20:15" in text
