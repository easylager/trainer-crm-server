"""TASK-328 AC6: текст уведомления колокольчика и ответ бота на /start watch_<id>."""

from __future__ import annotations

import re
from datetime import date, time

import pytest

from src.application.ice_watch_message import (
    NBSP,
    compose_new_schedule_message,
    compose_schedule_change_message,
    compose_watch_subscribed_reply,
    format_dates_range,
    format_nearest,
    open_ice_in_city_button,
    place_name,
)

# Суббота.
TODAY = date(2026, 10, 24)


def _plain(text: str) -> str:
    return text.replace(NBSP, " ")


def test_message_matches_contract_example() -> None:
    msg = compose_new_schedule_message(
        arena_name="Юность",
        first_date=date(2026, 10, 31),
        last_date=date(2026, 11, 6),
        nearest_date=date(2026, 10, 31),
        nearest_time=time(17, 0),
        today=TODAY,
    )
    assert _plain(msg) == (
        "<b>Юность: новое расписание</b>\n"
        "Сеансы на 31 октября – 6 ноября.\n"
        "Ближайший — в субботу, 31 октября, 17:00."
    )


def test_one_day_and_one_month_ranges() -> None:
    assert _plain(format_dates_range(date(2026, 10, 31), date(2026, 10, 31))) == "31 октября"
    assert _plain(format_dates_range(date(2026, 11, 2), date(2026, 11, 8))) == "2–8 ноября"
    assert _plain(format_dates_range(date(2026, 12, 28), date(2027, 1, 3))) == "28 декабря – 3 января"


def test_nearest_today_tomorrow_and_weekday_prepositions() -> None:
    assert _plain(format_nearest(TODAY, time(17, 0), today=TODAY)) == "сегодня в 17:00"
    assert _plain(format_nearest(date(2026, 10, 25), time(9, 30), today=TODAY)) == "завтра в 9:30"
    assert _plain(format_nearest(date(2026, 10, 27), time(18, 0), today=TODAY)) == "во вторник, 27 октября, 18:00"
    assert _plain(format_nearest(date(2026, 10, 28), time(18, 0), today=TODAY)) == "в среду, 28 октября, 18:00"


def test_today_variant_in_full_message() -> None:
    msg = compose_new_schedule_message(
        arena_name="Юность",
        first_date=TODAY,
        last_date=TODAY,
        nearest_date=TODAY,
        nearest_time=time(17, 0),
        today=TODAY,
    )
    assert _plain(msg).endswith("Сеансы на 24 октября.\nБлижайший — сегодня в 17:00.")


def test_typography_nbsp_no_emoji_no_brand() -> None:
    msg = compose_new_schedule_message(
        arena_name="Юность",
        first_date=date(2026, 10, 31),
        last_date=date(2026, 11, 6),
        nearest_date=date(2026, 11, 1),
        nearest_time=time(9, 0),
        today=TODAY,
    )
    assert f"на{NBSP}31{NBSP}октября" in msg
    assert f"в{NBSP}воскресенье, 1{NBSP}ноября, 9:00" in msg
    assert "09:00" not in msg
    assert "ICING" not in msg
    assert not re.search(r"\d{4}-\d{2}-\d{2}", msg)
    assert all(ord(ch) < 0x2600 for ch in msg), "emoji in message"
    assert '"' not in msg


# Реальные имена из прода → как в заголовке страницы места на сайте, без своих кавычек.
REAL_NAMES = [
    ("ТЦ Замок", "ТЦ Замок"),
    ('Каток хк "Юность"', "Каток ХК «Юность»"),
    ("ЛД «Гранд Каньон Айс»", "ЛД «Гранд Каньон Айс»"),
    ("Ледовый комплекс «Шанс Арена»", "Ледовый комплекс «Шанс Арена»"),
    ("Гомельский ледовый дворец спорта", "Гомельский ледовый дворец спорта"),
]


@pytest.mark.parametrize(("raw", "shown"), REAL_NAMES)
def test_real_names_as_on_site_header(raw: str, shown: str) -> None:
    from src.shared.public_display import format_public_name

    assert place_name(raw) == shown == format_public_name(raw)
    msg = compose_new_schedule_message(
        arena_name=raw,
        first_date=date(2026, 10, 31),
        last_date=date(2026, 11, 6),
        nearest_date=date(2026, 10, 31),
        nearest_time=time(17, 0),
        today=TODAY,
    )
    assert msg.startswith(f"<b>{shown}: новое расписание</b>\n")
    assert "„" not in msg and "“" not in msg and "««" not in msg
    shown_q = shown if shown.startswith("«") and shown.endswith("»") else f"«{shown}»"
    assert _plain(compose_watch_subscribed_reply(raw)) == (
        f"<b>{shown_q}: следим</b>\nНапишем, когда расписание обновится."
    )


def test_open_ice_in_city_button_uses_locative() -> None:
    assert open_ice_in_city_button("Минск").replace(NBSP, " ") == "Лёд в Минске"
    assert open_ice_in_city_button("Гомель").replace(NBSP, " ") == "Лёд в Гомеле"
    assert open_ice_in_city_button("Превьюск").replace(NBSP, " ") == "Лёд в городе Превьюск"
    assert open_ice_in_city_button("") == "Открыть расписание"


def test_schedule_change_message_reads_like_a_schedule() -> None:
    """Город и адрес в шапке, новые сеансы по дням с началом и концом, общая цена одной строкой, отменённые отдельно."""
    from src.application.ice_watch_message import WatchSession

    today = date(2026, 11, 20)
    s = dict(price_adult=1200, price_child=800, price_rental=500, currency="BYN")
    msg = compose_schedule_change_message(
        arena_name="Ледовая арена",
        city_name="Брест",
        address="ул. Московская, 151",
        today=today,
        added=[
            WatchSession(day=today, starts=time(14, 15), ends=time(15, 45), **s),
            WatchSession(day=today, starts=time(21, 15), ends=time(22, 45), **s),
            WatchSession(day=date(2026, 11, 21), starts=time(12, 0), ends=time(13, 30), **s),
        ],
        removed=[WatchSession(day=today, starts=time(18, 0))],
    )
    assert _plain(msg) == (
        "<b>Ледовая арена</b>\n"
        "Брест · ул. Московская, 151\n\n"
        "<b>Новые сеансы массового катания</b>\n"
        "Сегодня, 20 ноября\n14:15–15:45\n21:15–22:45\n"
        "Завтра, 21 ноября\n12:00–13:30\n\n"
        "Цена: взрослый 12 BYN · детский 8 BYN · прокат 5 BYN\n\n"
        "<b>Отменили</b>\n"
        "Сегодня, 20 ноября, 18:00"
    )


def test_schedule_change_message_puts_different_prices_on_each_line() -> None:
    from src.application.ice_watch_message import WatchSession

    today = date(2026, 11, 20)
    msg = _plain(
        compose_schedule_change_message(
            arena_name="Каток",
            today=today,
            added=[
                WatchSession(day=date(2026, 11, 23), starts=time(19, 0), ends=time(20, 30), price=1050, kind="open_ice"),
                WatchSession(day=date(2026, 11, 23), starts=time(21, 0), ends=None, price=900),
            ],
            removed=[],
        )
    )
    assert "<b>Новые сеансы</b>" in msg and "Понедельник, 23 ноября" in msg
    assert "19:00–20:30 · 10,50 BYN" in msg and "21:00 · 9 BYN" in msg and "Цена:" not in msg



def test_place_name_is_html_escaped() -> None:
    assert place_name("A & <B>") == "A &amp; &lt;B&gt;"
    assert place_name("") == "Каток"
