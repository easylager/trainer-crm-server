"""TASK-243: адрес, телефон, день и имя на выводе. Данные не меняются."""

from datetime import date

from src.shared.public_display import (
    format_phone_display,
    format_place_address,
    format_public_name,
    format_street_address,
    sentence_when,
    session_day_phrase,
)


TODAY = date(2026, 10, 13)  # вторник


def test_c4_session_day_phrase() -> None:
    assert session_day_phrase(TODAY, "12:45", today=TODAY) == "сегодня 12:45"
    assert session_day_phrase(date(2026, 10, 14), "08:30", today=TODAY) == "завтра 8:30"
    assert session_day_phrase(date(2026, 10, 15), "10:30", today=TODAY) == "чт 10:30"


def test_c5_sentence_when_is_lowercase_mid_phrase() -> None:
    assert sentence_when(date(2026, 10, 14), "09:00", today=TODAY) == "завтра, 9:00"
    assert sentence_when(TODAY, "14:00", today=TODAY) == "сегодня, 14:00"


def test_c6_street_drops_city_and_region_place_keeps_city() -> None:
    raw = "ул. Ташкентская 19, Минск, Минская область"
    assert format_street_address(raw, city="Минск") == "ул. Ташкентская, 19"
    assert format_place_address(raw, city="Минск") == "ул. Ташкентская, 19, Минск"
    assert format_street_address("г. Минск, пр-т. Победителей 65", city="Минск") == "пр-т Победителей, 65"


def test_c7_prospekt_abbreviation() -> None:
    assert format_street_address("пр-т. Победителей, 14", city="Минск") == "пр-т Победителей, 14"
    assert "ул." in format_street_address("ул. Ленина, 1", city="Минск")


def test_c8_phone_display_keeps_plus_groups() -> None:
    assert format_phone_display("+375293300749") == "+375 29 330-07-49"
    assert format_phone_display("+375 29 330-07-49") == "+375 29 330-07-49"
    assert format_phone_display("+79991234567") == "+7 999 123-45-67"


def test_c10_names_quotes_hk_and_spb() -> None:
    assert format_public_name('Каток хк "Юность"') == "Каток ХК «Юность»"
    assert format_public_name("Каток Приорбанк | Visa") == "Каток Приорбанк | Visa"
    assert format_public_name("Санкт-Петербург/ЛО") == "Санкт-Петербург"
