"""TASK-424: строка-ответ у расписания и штамп «Проверено» — на сетках катков Минска 16.11.2026."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import pytest

from src.application import rink_brief
from src.application.rink_brief import (
    ohm_line,
    proof_stamp,
    schedule_line,
    weekend_price_note,
)

TODAY = date(2026, 11, 16)  # понедельник


def _s(offset: int, start: str, minutes: int = 60, price: int | None = None) -> dict:
    h, m = (int(x) for x in start.split(":"))
    end = h * 60 + m + minutes
    return {
        "local_date": (TODAY + timedelta(days=offset)).isoformat(),
        "starts_at_local": f"{h:02d}:{m:02d}:00",
        "ends_at_local": f"{end // 60:02d}:{end % 60:02d}:00",
        "price_adult_minor": price,
    }


def _zamok(first_today: int = 10) -> list[dict]:
    rows = []
    for offset in range(7):
        weekend = (TODAY + timedelta(days=offset)).weekday() >= 5
        for hour in range(first_today if offset == 0 else 10, 23):
            rows.append(_s(offset, f"{hour}:15", 45, 1100 if weekend else 1000))
    return rows


# Ледовый дворец, массовое: пн 20:00, ср 20:15, чт 19:45, пт 19:30, сб 18:00/19:20/20:35, вс 18:00/19:20.
LEDBY = [
    _s(0, "20:00"),
    _s(2, "20:15"),
    _s(3, "19:45"),
    _s(4, "19:30"),
    _s(5, "18:00"),
    _s(5, "19:20"),
    _s(5, "20:35"),
    _s(6, "18:00"),
    _s(6, "19:20"),
]
# Ледовый дворец, ОХМ: пн 12:45, вт/чт/вс 13:00.
LEDBY_OHM = [_s(0, "12:45"), _s(1, "13:00"), _s(3, "13:00"), _s(6, "13:00")]
# Чижовка: сайт выложил только пн–ср.
CHIZHOVKA = [
    _s(0, "9:30"),
    _s(0, "19:00"),
    _s(1, "9:30"),
    _s(1, "13:30"),
    _s(1, "19:00"),
    _s(2, "13:30"),
    _s(2, "19:00"),
]
# DiaMond: сеансы пн–пт, на выходные пусто — публикация не доказана полной.
DIAMOND = [_s(o, t, 45) for o in range(5) for t in ("11:00", "11:45", "12:45", "13:45", "16:45", "21:15")]


def test_even_daily_grid_reads_as_every_hour() -> None:
    assert schedule_line(_zamok(), today=TODAY) == "Каждый день 13 сеансов по 45 минут — каждый час с 10:15 до 22:15."


def test_afternoon_today_does_not_shrink_the_daily_count() -> None:
    # Начавшиеся сеансы в окно не попадают: в 15:00 сегодня осталось 8 — это та же сетка.
    assert schedule_line(_zamok(first_today=15), today=TODAY) == schedule_line(_zamok(), today=TODAY)


def test_irregular_week_names_days_and_range() -> None:
    assert schedule_line(LEDBY, today=TODAY) == (
        "Пн и ср–вс, только вечером: 1–3 сеанса в день по 60 минут, начало с 18:00 до 20:35."
    )


def test_partial_publication_names_no_weekdays() -> None:
    line = schedule_line(CHIZHOVKA, today=TODAY)
    assert line == "Сеансы по 60 минут — в 9:30, 13:30 и 19:00."
    assert not re.search(r"\b(пн|вт|ср|чт|пт|сб|вс|будням|каждый день)\b", line)
    assert schedule_line(DIAMOND, today=TODAY) == "Сеансы по 45 минут — начало с 11:00 до 21:15."


def test_unknown_today_weekday_falls_back_to_partial() -> None:
    # Вечером сегодняшних сеансов уже нет: про понедельник ничего не известно — «каждый день» нельзя.
    rows = [r for r in _zamok() if r["local_date"] != TODAY.isoformat()]
    assert schedule_line(rows, today=TODAY) == "Сеансы по 45 минут — каждый час с 10:15 до 22:15."


def test_ohm_line_single_session_days() -> None:
    assert (
        ohm_line(LEDBY_OHM, today=TODAY) == "ОХМ: пн, вт, чт и вс — один сеанс в день по 60 минут, в 12:45 или 13:00."
    )


def test_no_sessions_no_line() -> None:
    assert schedule_line([], today=TODAY) is None
    assert ohm_line([], today=TODAY) is None
    # Сеанс за пределами недели — тоже не повод для строки.
    assert schedule_line([_s(9, "12:00")], today=TODAY) is None


def test_lines_have_no_dates_or_relative_days() -> None:
    lines = [schedule_line(rows, today=TODAY) for rows in (_zamok(), LEDBY, CHIZHOVKA, DIAMOND)]
    lines.append(ohm_line(LEDBY_OHM, today=TODAY))
    for line in lines:
        assert line
        assert not re.search(r"сегодня|завтра|\d{1,2}\.\d{2}|\b(ноя|дек|янв)", line, re.I), line


def test_lines_are_unique_across_minsk_rinks() -> None:
    lines = [schedule_line(rows, today=TODAY) for rows in (_zamok(), LEDBY, CHIZHOVKA, DIAMOND)]
    assert len(set(lines)) == len(lines)


def test_length_cap_falls_back_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    assert all(len(schedule_line(r, today=TODAY)) <= rink_brief.BRIEF_MAX for r in (_zamok(), LEDBY, DIAMOND))
    monkeypatch.setattr(rink_brief, "BRIEF_MAX", 60)
    assert schedule_line(_zamok(), today=TODAY) == "Сеансы по 45 минут — каждый час с 10:15 до 22:15."
    monkeypatch.setattr(rink_brief, "BRIEF_MAX", 10)
    assert schedule_line(_zamok(), today=TODAY) is None


def test_weekend_price_only_when_it_differs() -> None:
    assert weekend_price_note(_zamok(), currency="BYN") == "В сб и вс взрослый — 11 BYN."
    assert weekend_price_note(LEDBY, currency="BYN") is None  # без цен в сеансах
    flat = [{**r, "price_adult_minor": 1000} for r in _zamok()]
    assert weekend_price_note(flat, currency="BYN") is None


NOW = datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc)  # 10:00 по Минску


def _fresh(**kw) -> dict:
    base = {
        "schedule_observed_at": "2026-11-15T23:04:27+00:00",  # 16.11 02:04 по Минску
        "schedule_auto": True,
        "schedule_stale": False,
        "source_url": "https://tczamok.by/entertainments/ice-rink",
    }
    base.update(kw)
    return base


def test_stamp_for_fresh_parsed_schedule_names_minsk_date_and_source() -> None:
    stamp = proof_stamp(_fresh(), now=NOW)
    assert stamp is not None
    assert stamp.day_label == "16.11"
    assert stamp.source_url == "https://tczamok.by/entertainments/ice-rink"


def test_no_stamp_for_stale_or_old_parsed_schedule() -> None:
    assert proof_stamp(_fresh(schedule_stale=True), now=NOW) is None
    assert proof_stamp(_fresh(schedule_observed_at="2026-11-13T23:00:00+00:00"), now=NOW) is None
    assert proof_stamp(_fresh(schedule_observed_at=None), now=NOW) is None
    assert proof_stamp(None, now=NOW) is None


def test_manual_schedule_stamp_only_within_three_days_and_without_source() -> None:
    two_days = proof_stamp(_fresh(schedule_auto=False, schedule_observed_at="2026-11-14T09:41:00+00:00"), now=NOW)
    assert two_days is not None and two_days.day_label == "14.11" and two_days.source_url is None
    # Минск Арена: ручное расписание от 05.11 — без штампа.
    assert proof_stamp(_fresh(schedule_auto=False, schedule_observed_at="2026-11-05T11:16:00+00:00"), now=NOW) is None


def test_admin_site_source_gives_the_link_even_without_parser_job() -> None:
    # Превью/прод без задания парсера: источник «сайт катка» записан админом — ссылка есть.
    site = "https://tczamok.by/entertainments/ice-rink"
    stamp = proof_stamp(_fresh(schedule_auto=False, source_url=None, schedule_site_url=site), now=NOW)
    assert stamp is not None and stamp.source_url == site
    # Ручное расписание без записанного сайта — штамп без ссылки.
    plain = proof_stamp(_fresh(schedule_auto=False, schedule_site_url=None), now=NOW)
    assert plain is not None and plain.source_url is None


def test_schedule_site_url_only_for_collected_site_sources() -> None:
    from src.application.arena_public_use_cases import _schedule_site_url

    url = "https://led.by/"
    assert (
        _schedule_site_url(
            {"schedule_source_url": url, "schedule_source_kind": "site", "schedule_fetch_mode": "server"}
        )
        == url
    )
    assert (
        _schedule_site_url({"schedule_source_url": url, "schedule_source_kind": None, "schedule_fetch_mode": "manual"})
        == url
    )
    assert (
        _schedule_site_url({"schedule_source_url": url, "schedule_source_kind": "site", "schedule_fetch_mode": "none"})
        is None
    )
    ig = "https://www.instagram.com/rink/"
    assert (
        _schedule_site_url(
            {"schedule_source_url": ig, "schedule_source_kind": "instagram", "schedule_fetch_mode": "manual"}
        )
        is None
    )
    assert _schedule_site_url({}) is None
