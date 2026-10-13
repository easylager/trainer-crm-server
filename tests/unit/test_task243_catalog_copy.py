"""TASK-243 AC-2/AC-3: хаб, 404 города и видимый текст без оговорок."""

import re
from datetime import datetime, timezone

from src.application.city_hub_page import (
    _hero_sub,
    _quick_html,
    _roller_hall_count,
    _trainers_route,
    city_hub_description,
)
from src.application.ice_city_day import CITY_SLUG_ALIASES, render_unknown_city_html
from src.application.ice_city_day_page import render_ice_city_day_page
from src.application.selection_page import _service_chips_html

_BANNED = ("уточн", "обычно", "с сайта катка", "проверила команда", "Размер точки", "Нажмите на время")


def visible_text(html: str) -> str:
    stripped = re.sub(r"(?is)<script[\s\S]*?</script>", " ", html)
    stripped = re.sub(r"(?is)<style[\s\S]*?</style>", " ", stripped)
    return re.sub(r"<[^>]+>", " ", stripped)


def assert_public_copy(html: str) -> None:
    text = visible_text(html)
    folded = text.casefold()
    for needle in _BANNED:
        assert needle.casefold() not in folded, needle
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
    assert " ," not in text and " ." not in text


def _hub_view(**extra):
    view = {
        "city": {"id": 1, "name": "Минск"},
        "slug": "minsk",
        "place_count": 27,
        "rink_count": 14,
        "places": [{"venue_type": "ice", "name": "Каток"}, {"venue_type": "shop", "name": "Магазин"}],
        "skate_counts": {"today": 3, "tomorrow": 0, "weekend": 1, "all": 138},
        "ohm_counts": {"all": 0},
        "trainer_count": 3,
        "trainer_roles": ["тренер"],
        "now": datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc),
    }
    view.update(extra)
    return view


def test_a1_trainer_count_is_a_russian_phrase() -> None:
    html = _trainers_route(_hub_view(), href="/trainers")
    assert "3 тренера" in html
    assert "›" not in html


def test_a2_roller_hint_only_when_count_is_zero() -> None:
    places = [{"venue_type": "other", "name": "Лыжероллерная трасса"}]
    assert _roller_hall_count(places) == 1
    assert _roller_hall_count([{"venue_type": "ice", "name": "Чижовка"}]) == 0


def test_a3_description_uses_place_count_not_rink_count() -> None:
    text = city_hub_description(_hub_view())
    assert text.startswith("27 мест")
    assert "14" not in text


def test_a6_punctuation_sits_inside_the_same_node() -> None:
    html = _hero_sub(_hub_view())
    assert " ," not in visible_text(html)
    assert " ." not in visible_text(html)


def test_a7_zero_window_is_inactive_dash() -> None:
    html = _quick_html("minsk", {"today": 2, "tomorrow": 0, "weekend": 1}, hot=None, all_count=4, t="ice")
    assert "Завтра <small>—</small>" in html
    assert "Завтра <small>0</small>" not in html
    assert "Все <small>4</small>" in html


def test_a8_unknown_city_lists_cities_and_alias_is_declared() -> None:
    html = render_unknown_city_html(
        [{"name": "Минск"}, {"name": "Санкт-Петербург/ЛО"}],
        home="/",
    )
    assert "Такого города нет в каталоге" in html
    assert "Этого места больше нет" not in html
    assert 'href="/c/minsk"' in html
    assert 'href="/c/sankt-peterburg-lo"' in html
    assert "Санкт-Петербург" in html
    assert "/ЛО" not in html
    assert CITY_SLUG_ALIASES["sankt-peterburg"] == "sankt-peterburg-lo"
    assert_public_copy(html)


def test_a10_service_chips_drop_the_duplicate_all_services() -> None:
    html = _service_chips_html({"svc": "service"}, city_name="Минск")
    assert "Все услуги" not in html
    assert "Заточка" in html
    assert "Прокат" in html


def test_ac2_ice_today_visible_text() -> None:
    html = render_ice_city_day_page(
        city_name="Минск",
        day={
            "day_label": "сегодня",
            "local_date": "2026-10-13",
            "session_count": 17,
            "arena_count": 4,
            "arenas": [
                {
                    "name": 'Каток хк "Юность"',
                    "slug": "yunost",
                    "district": "",
                    "address": "ул. Ташкентская 19, Минск, Минская область",
                    "sessions": [
                        {
                            "starts_at_local": "12:45",
                            "ends_at_local": "13:45",
                            "price_adult": "8 BYN",
                            "schedule_basis": "projected",
                        }
                    ],
                    "phone": "+375293300749",
                }
            ],
            "unconfirmed": [],
        },
        canonical_url="https://example.test/ice/minsk/today",
        og_image_url="https://example.test/og.png",
        cta_url=None,
    )
    text = visible_text(html)
    assert_public_copy(html)
    assert "Минск: лёд сегодня" in text
    assert "17 сеансов сегодня" in text
    assert "2026-10-13" not in text
    assert "Каток ХК «Юность»" in text
    assert "ул. Ташкентская 19" in text
    assert "Минская область" not in text
    assert "Glide ·" not in text
