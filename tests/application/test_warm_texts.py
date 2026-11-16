"""TASK-428: тексты прогрева и предложения подписки — правила craft-guide тест-грепом и склонения."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from src.application import warm_texts as wt
from src.ingestion.hockey_sources import MINSK_TZ
from src.shared.copy_ru import COPY

NB = "\u00a0"
NOW = datetime(2026, 11, 19, 9, 30, tzinfo=MINSK_TZ)  # четверг
KEYS = [k for k in COPY if k.startswith(("warm.", "watch_offer."))]
FORBIDDEN = (
    "!",
    '"',
    " ,",
    " .",
    "уточн",
    "обычно",
    "с сайта",
    "провер",
    "успей",
    "не упусти",
    "эксклюзив",
    "лучш",
    "скучаем",
    "давно не",
    "вернись",
    "нажмите",
    "слот",
    "карточк",
    "каталог",  # внутреннее слово; «Этого катка больше нет в каталоге» — исключение ниже
    "BYN",
    "р.",
)
_EMOJI = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf]")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _samples() -> list[str]:
    starts = [NOW + timedelta(hours=h) for h in (2, 5, 9)] + [NOW + timedelta(days=d, hours=3) for d in (1, 2, 4)]
    many = [NOW + timedelta(hours=2, minutes=30 * i) for i in range(7)]
    return [
        wt.welcome_text(arena_name="Чижовка-арена", starts=starts, now=NOW),
        wt.welcome_text(arena_name='Каток хк "Юность"', starts=starts[:1], now=NOW),
        wt.welcome_text(arena_name="Минск-Арена", starts=[], now=NOW),
        wt.today_text(arena_name="Чижовка-арена", starts=many, now=NOW) or "",
        wt.week_text(arena_name="Чижовка-арена", starts=starts + many, now=NOW) or "",
        wt.nudge_text(arena_name="ЛД «Гранд Каньон Айс»"),
    ]


def test_copy_keys_exist() -> None:
    assert len(KEYS) >= 20


@pytest.mark.parametrize("key", KEYS)
def test_copy_rules(key: str) -> None:
    value = COPY[key]
    assert not _EMOJI.search(value), key
    assert not _ISO_DATE.search(value), key
    lowered = value.lower()
    for word in FORBIDDEN:
        if key == "warm.sub_gone" and word == "каталог":
            continue
        assert word.lower() not in lowered, (key, word)


@pytest.mark.parametrize("body", _samples())
def test_rendered_rules(body: str) -> None:
    assert body and "!" not in body and '"' not in body and " ," not in body
    assert not _EMOJI.search(body) and not _ISO_DATE.search(body)
    assert re.search(r"\b0\d:\d\d", body) is None  # время без ведущего нуля
    assert " в " not in body and " и " not in body  # после «в» и «и» — неразрывный пробел


def test_names_get_quotes_once() -> None:
    assert wt.arena_title("Чижовка-арена") == "«Чижовка-арена»"
    assert wt.arena_title("ЛД «Гранд Каньон Айс»") == "ЛД «Гранд Каньон Айс»"
    assert wt.arena_title("<script>") == "«&lt;script&gt;»"


@pytest.mark.parametrize(("n", "word"), [(1, "сеанс"), (2, "сеанса"), (5, "сеансов"), (11, "сеансов"), (21, "сеанс")])
def test_plural(n: int, word: str) -> None:
    assert wt.session_word(n) == word


def test_times_phrase() -> None:
    t = [NOW.replace(hour=h, minute=0) for h in (9, 12, 15, 17, 19, 21)]
    assert wt.times_phrase(t[:1]) == "9:00"
    assert wt.times_phrase(t[:2]) == "9:00 и 12:00"
    assert wt.times_phrase(t[:3]) == "9:00, 12:00 и 15:00"
    assert wt.times_phrase(t) == "9:00, 12:00, 15:00, 17:00 и ещё 2 сеанса"


def test_day_phrases() -> None:
    today = NOW.date()
    assert wt.day_phrase(today, today) == "сегодня"
    assert wt.day_phrase(today + timedelta(days=1), today) == "завтра"
    assert wt.day_phrase(today + timedelta(days=5), today) == "во вторник"
    assert wt.day_phrase(today + timedelta(days=9), today) == "28 ноября"


def test_today_and_week_are_silent_without_sessions() -> None:
    past = [NOW - timedelta(hours=1)]
    assert wt.today_text(arena_name="X", starts=past, now=NOW) is None
    assert wt.week_text(arena_name="X", starts=[], now=NOW) is None
    tomorrow_only = [NOW + timedelta(days=1)]
    assert wt.today_text(arena_name="X", starts=tomorrow_only, now=NOW) is None


def test_week_shows_at_most_five_days() -> None:
    starts = [NOW + timedelta(days=d, hours=2) for d in range(7)]
    body = wt.week_text(arena_name="X", starts=starts, now=NOW) or ""
    assert body.count("• ") == wt.WEEK_DAYS_SHOWN
