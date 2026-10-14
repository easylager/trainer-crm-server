"""Подборка /c/: карточка места несёт тот же кадр, что мини-карточка каталога."""

from datetime import date, timedelta

from src.application.place_card_image import selection_story_board, selection_story_rows
from src.application.selection_page import _place_html, _place_photo_url


def test_place_card_uses_list_card_photo() -> None:
    html = _place_html(
        {
            "id": 3,
            "name": "ТЦ Замок",
            "slug": "tts-zamok",
            "district": "Центральный",
            "address": "пр-т Победителей, 65",
            "card": "/api/public/photos/arenas/3/x_card.jpg",
            "thumb": "/api/public/photos/arenas/3/x_thumb.jpg",
            "venue_icon": "❄️",
        },
        city_name="Минск",
        slots=[],
    )
    assert 'class="pick__photo"' in html
    assert "/api/public/photos/arenas/3/x_card.jpg" in html
    assert "❄️" not in html
    assert "pick__icon" not in html


def test_place_card_without_photo_has_type_icon_not_empty_hole() -> None:
    html = _place_html(
        {
            "id": 1,
            "name": "Юность",
            "slug": "yunost",
            "venue_icon": "❄️",
            "live_line": "завтра 10:00",
        },
        city_name="Минск",
        slots=[],
    )
    assert "pick__photo" not in html
    assert "pick__icon" in html
    assert "<svg" in html
    assert "❄️" not in html


def test_place_photo_url_skips_javascript_and_empty() -> None:
    assert _place_photo_url({"card": "javascript:alert(1)", "thumb": "/t.jpg"}) == "/t.jpg"
    assert _place_photo_url({}) is None


def test_story_rows_drop_places_without_a_session() -> None:
    today = date(2026, 10, 12)
    view = {
        "skating": True,
        "session_count": 2,
        "items": [
            {"id": 1, "name": "ТЦ Замок"},
            {"id": 2, "name": "Lifestyle"},
            {"id": 3, "name": "ТЦ DiaMond city"},
            {"id": 4, "name": "Ледовый дворец"},
        ],
        "slots": {
            3: [{"local_date": today, "starts_at_local": "13:30"}],
            4: [{"local_date": today, "starts_at_local": "20:00"}],
        },
    }
    board = selection_story_board(view, today=today)
    assert board["headline"] == "Сегодня вечером"
    assert board["rows"] == [("Ледовый дворец", "20:00")]
    assert board["note"] == "днём ещё 1"
    assert "ТЦ Замок" not in str(board["rows"])
    assert "Lifestyle" not in str(board["rows"])
    assert selection_story_rows(view, today=today) == board["rows"]


def test_story_board_leads_with_this_evening_and_points_at_the_rest() -> None:
    today = date(2026, 10, 12)
    view = {
        "skating": True,
        "session_count": 6,
        "items": [
            {"id": 1, "name": "DiaMond"},
            {"id": 2, "name": "Ледовый"},
            {"id": 3, "name": "Пустой"},
        ],
        "slots": {
            1: [
                {"local_date": today, "starts_at_local": "13:30"},
                {"local_date": today, "starts_at_local": "16:30"},
                {"local_date": today, "starts_at_local": "21:15"},
                {"local_date": today + timedelta(days=1), "starts_at_local": "11:00"},
            ],
            2: [{"local_date": today, "starts_at_local": "20:00"}],
        },
    }
    board = selection_story_board(view, today=today)
    assert board["headline"] == "Сегодня вечером"
    assert board["rows"] == [
        ("DiaMond", "16:30"),
        ("Ледовый", "20:00"),
        ("DiaMond", "21:15"),
    ]
    assert board["note"] == "днём ещё 1 · в другие дни ещё 1"
    assert board["image_cta"] == "Все 6 сеансов — сканируй QR"
    assert board["text_cta"] == "Все 6 сеансов — по ссылке"
    assert "Пустой" not in str(board["rows"])


def test_story_rows_name_places_when_the_city_has_no_ice() -> None:
    view = {
        "skating": True,
        "items": [{"id": 1, "name": "Ледовый"}, {"id": 2, "name": "Зал Силы"}],
        "slots": {},
    }
    assert selection_story_rows(view) == [("Ледовый", ""), ("Зал Силы", "")]


def test_story_rows_keep_shops_when_the_list_is_not_about_ice() -> None:
    view = {"skating": False, "items": [{"id": 1, "name": "Мастерская"}], "slots": {}}
    assert selection_story_rows(view) == [("Мастерская", "")]


def test_share_page_hides_broken_photo_and_stays_light() -> None:
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "static" / "share" / "place.html").read_text(
        encoding="utf-8"
    )
    assert "dropBrokenPhoto" in html
    assert "color-scheme: light;" in html
    assert "prefers-color-scheme: dark" not in html
