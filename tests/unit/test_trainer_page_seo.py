"""title/description/H1 страницы тренера: город в предложном, короткие направления, только лёд."""

from __future__ import annotations

from src.application.site_trainer_page import (
    DESCRIPTION_LIMIT,
    TITLE_LIMIT,
    jsonld,
    page_description,
    page_heading,
    page_title,
    trainer_place_phrase,
)
from src.shared.city_locative import city_locative


def _page(**over):
    base = {
        "name": "Александр Гаевский",
        "city_name": "Минск",
        "directions": [{"key": "zero"}, {"key": "better"}],
        "arenas": [{"name": "Замок", "is_ice": True}, {"name": "Минск-Арена", "is_ice": True}],
        "min_price": (4187, "BYN"),
        "can_book": True,
    }
    return {**base, **over}


def test_title_adds_brand_only_when_the_whole_line_fits() -> None:
    short = page_title(_page(name="Влад Сак"))
    assert short == "Влад Сак — тренер по катанию на коньках в Минске · Glideclub"
    assert len(short) <= TITLE_LIMIT
    long = page_title(_page())
    assert long == "Александр Гаевский — тренер по катанию на коньках в Минске"
    assert "Glideclub" not in long
    assert page_heading(_page()) == long


def test_unknown_city_is_not_declined_into_the_nominative() -> None:
    assert city_locative("Заславль") is None
    phrase = trainer_place_phrase("Заславль")
    assert phrase == "тренер по катанию на коньках"
    assert "в Заславль" not in phrase


def test_title_uses_public_city_not_the_internal_region_label() -> None:
    title = page_title(_page(name="Мария Соколова", city_name="Санкт-Петербург/ЛО"))
    assert title == "Мария Соколова — тренер по катанию на коньках в Санкт-Петербурге"
    assert "Санкт-Петербург/ЛО" not in title
    assert "Glideclub" not in title


def test_description_two_directions_keeps_both_rinks_when_they_fit() -> None:
    d = page_description(_page())
    assert d == (
        "Александр Гаевский — тренер по катанию на коньках в Минске: с нуля и для уже катающихся. "
        "Катки: Замок, Минск-Арена. От 41,87 BYN за занятие, запись в Telegram."
    )
    assert len(d) <= DESCRIPTION_LIMIT


def test_description_one_direction_keeps_both_rinks_and_price() -> None:
    d = page_description(_page(directions=[{"key": "zero"}]))
    assert d == (
        "Александр Гаевский — тренер по катанию на коньках в Минске: с нуля. "
        "Катки: Замок, Минск-Арена. От 41,87 BYN за занятие, запись в Telegram."
    )


def test_description_keeps_two_rinks_when_there_is_no_price() -> None:
    d = page_description(_page(directions=[{"key": "zero"}], min_price=None))
    assert d == (
        "Александр Гаевский — тренер по катанию на коньках в Минске: с нуля. "
        "Катки: Замок, Минск-Арена. Запись в Telegram."
    )


def test_description_three_directions_drops_the_second_rink_and_keeps_price() -> None:
    d = page_description(_page(directions=[{"key": "hock"}, {"key": "zero"}, {"key": "better"}]))
    assert d == (
        "Александр Гаевский — тренер по катанию на коньках в Минске: "
        "с нуля, для уже катающихся и хоккейное катание. Каток: Замок. От 41,87 BYN за занятие, запись в Telegram."
    )
    assert "Минск-Арена" not in d
    assert len(d) <= DESCRIPTION_LIMIT


def test_description_spb_rubles_and_public_city() -> None:
    d = page_description(
        _page(
            name="Мария Соколова",
            city_name="Санкт-Петербург/ЛО",
            directions=[{"key": "fig"}],
            arenas=[{"name": "Ледовый дворец", "is_ice": True}],
            min_price=(150000, "RUB"),
        )
    )
    assert d == (
        "Мария Соколова — тренер по катанию на коньках в Санкт-Петербурге: фигурное катание. "
        "Каток: Ледовый дворец. От 1500 руб. за занятие, запись в Telegram."
    )
    assert "Санкт-Петербург/ЛО" not in d


def test_description_skips_a_venue_without_ice() -> None:
    d = page_description(
        _page(
            directions=[{"key": "zero"}],
            arenas=[
                {"name": "Лыжероллерная трасса", "is_ice": False},
                {"name": "ТЦ Замок", "is_ice": True},
            ],
            min_price=(2500, "BYN"),
        )
    )
    assert "Лыжероллерная" not in d
    assert "Каток: ТЦ Замок." in d
    assert d.count("«") == d.count("»")


def test_description_keeps_paired_quotes_and_telegram_without_booking() -> None:
    d = page_description(
        _page(
            directions=[{"key": "zero"}],
            arenas=[{"name": "ТЦ «Замок»", "is_ice": True}],
            min_price=None,
            can_book=False,
        )
    )
    assert "ТЦ «Замок»" in d
    assert d.count("«") == d.count("»")
    assert d.endswith("Запись в Telegram.")
    assert "…" not in d


def test_description_long_rink_name_is_not_cut_mid_word() -> None:
    d = page_description(
        _page(
            name="Константин Александрович Иванов-Петровский-Сидоренко",
            arenas=[{"name": "Ледовый дворец спорта имени Очень Длинного Названия", "is_ice": True}],
            directions=[{"key": "zero"}, {"key": "better"}, {"key": "fig"}, {"key": "hock"}],
        )
    )
    assert d == (
        "Константин Александрович Иванов-Петровский-Сидоренко — тренер по катанию на коньках в Минске: "
        "с нуля, для уже катающихся и фигурное катание. Запись в Telegram."
    )
    assert len(d) <= DESCRIPTION_LIMIT
    assert "…" not in d
    assert "Длинного" not in d
    assert d.count("«") == d.count("»")


def test_jsonld_job_title_matches_the_heading_phrase() -> None:
    page = _page(city_name="Санкт-Петербург/ЛО")
    payload = jsonld(page, canonical="https://glide.example/t/1-maria", base_url="https://glide.example")
    assert "тренер по катанию на коньках в Санкт-Петербурге" in payload
    assert "Санкт-Петербург/ЛО" not in payload
    assert page_heading(page).endswith("тренер по катанию на коньках в Санкт-Петербурге")
