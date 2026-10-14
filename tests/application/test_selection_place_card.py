"""Подборка /c/: карточка места несёт тот же кадр, что мини-карточка каталога."""

from datetime import date, timedelta

from src.application.place_card_image import selection_story_board, selection_story_rows
from src.application.selection_page import _place_html, _place_photo_url, compose_selection_share


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
    assert board["headline"] != "Сегодня вечером"
    assert "сеанс" in board["headline"]
    assert board["rows"] == [
        ("ТЦ DiaMond city", "Пн 13:30"),
        ("Ледовый дворец", "Пн 20:00"),
    ]
    assert board["note"] == ""
    assert "и ещё" not in board["image_cta"]
    assert board["image_cta"] == "Цены и адреса — сканируй QR"
    assert "ТЦ Замок" not in str(board["rows"])
    assert "Lifestyle" not in str(board["rows"])
    assert selection_story_rows(view, today=today) == board["rows"]


def test_story_board_of_the_whole_city_is_one_session_per_place() -> None:
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
    assert "Сегодня вечером" not in board["headline"]
    assert "в другие дни" not in board["note"]
    assert board["rows"] == [
        ("DiaMond", "Пн 13:30"),
        ("Ледовый", "Пн 20:00"),
    ]
    assert board["note"] == ""
    assert board["image_cta"] == "Все 6 сеансов — сканируй QR"
    assert board["text_cta"] == "Все 6 сеансов — по ссылке"
    assert "и ещё" not in board["image_cta"]
    assert "Пустой" not in str(board["rows"])


def _weekend_view() -> dict:
    sat, sun = date(2026, 10, 17), date(2026, 10, 18)
    return {
        "city": {"name": "Минск"},
        "skating": True,
        "session_count": 7,
        "window": {"key": "weekend", "from": "2026-10-17T00:00:00+03:00", "to": "2026-10-19T00:00:00+03:00"},
        "items": [
            {"id": 1, "name": "ТЦ Замок"},
            {"id": 2, "name": "ТЦ DiaMond city"},
            {"id": 3, "name": "Ледовый дворец"},
        ],
        "slots": {
            1: [{"local_date": sat, "starts_at_local": t} for t in ("10:15", "11:15", "12:15", "13:15")],
            2: [{"local_date": sat, "starts_at_local": "13:45"}],
            3: [{"local_date": sun, "starts_at_local": "09:00"}, {"local_date": sun, "starts_at_local": "18:00"}],
        },
    }


def test_weekend_board_shows_every_place_before_repeating_one() -> None:
    board = selection_story_board(_weekend_view(), today=date(2026, 10, 14))
    assert board["rows"][:3] == [
        ("ТЦ Замок", "Сб 10:15"),
        ("ТЦ DiaMond city", "Сб 13:45"),
        ("Ледовый дворец", "Вс 09:00"),
    ]
    assert len(board["rows"]) == 7


def test_weekend_share_text_names_the_dates_once() -> None:
    share = compose_selection_share(_weekend_view(), page_url="https://glide.example/c/minsk")
    assert share["share_text"].count("Сб, 17 окт – Вс, 18 окт") == 1


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
