"""TASK-328 AC6: текст уведомления колокольчика и ответ бота на /start watch_<id>."""

from __future__ import annotations

import re
from datetime import date, time

import pytest

from src.application.ice_watch_message import (
    NBSP,
    compose_new_schedule_message,
    compose_watch_subscribed_reply,
    format_dates_range,
    format_nearest,
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
    assert _plain(compose_watch_subscribed_reply(raw)) == (
        f"Готово: {shown}. Напишем один раз, когда появится новое расписание."
    )


def test_place_name_is_html_escaped() -> None:
    assert place_name("A & <B>") == "A &amp; &lt;B&gt;"
    assert place_name("") == "Каток"
