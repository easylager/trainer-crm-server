"""Часы прошлой зимы: все форматы seed 2025/26 -> расписание по дням (TASK-343)."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.shared.winter_hours import hours_summary_ru, parse_hours


def w(parsed, day):
    return parsed.opening_hours["weekly"][day]


@pytest.mark.parametrize("raw", ["7:00–23:00", "07:00–23:00", "7.00-23.00"])
def test_single_range_applies_to_every_day(raw):
    p = parse_hours(raw)
    assert p.known and p.mode == "daily"
    assert all(w(p, d) == [["07:00", "23:00"]] for d in ("mon", "wed", "sun"))


def test_dotted_with_spaces():
    assert w(parse_hours("9.00 - 20.00"), "tue") == [["09:00", "20:00"]]
    assert w(parse_hours("8.00 – 20.00"), "sun") == [["08:00", "20:00"]]


def test_weekday_weekend_split():
    p = parse_hours("пн-пт 17.00-21.00; сб-вс 11.00-22.00")
    assert p.mode == "weekly"
    assert w(p, "fri") == [["17:00", "21:00"]] and w(p, "sat") == [["11:00", "22:00"]]


def test_capitalised_days_and_spaces():
    p = parse_hours("Пн-Пт 14.00 - 21.00; Сб-Вс 12.00 - 21.00")
    assert w(p, "mon") == [["14:00", "21:00"]] and w(p, "sun") == [["12:00", "21:00"]]


def test_mixed_list_of_days():
    p = parse_hours("пн 11:00–23:00; вт,пт 10:00–23:00; ср,чт 12:00–23:00; сб-вс 8:30–23:00")
    assert w(p, "mon") == [["11:00", "23:00"]]
    assert w(p, "tue") == w(p, "fri") == [["10:00", "23:00"]]
    assert w(p, "thu") == [["12:00", "23:00"]]
    assert w(p, "sat") == w(p, "sun") == [["08:30", "23:00"]]


def test_partial_week_leaves_days_off():
    p = parse_hours("пн-сб 08:00–20:00; вс 10:00–19:00")
    assert w(p, "sat") == [["08:00", "20:00"]] and w(p, "sun") == [["10:00", "19:00"]]


def test_round_the_clock_only_when_stated():
    p = parse_hours("круглосуточно")
    assert p.known and p.mode == "24h" and w(p, "mon") == [["00:00", "24:00"]]
    assert hours_summary_ru(p.opening_hours) == "Круглосуточно"


@pytest.mark.parametrize("raw", ["", None, "   "])
def test_empty_is_unknown_never_24h(raw):
    p = parse_hours(raw)
    assert not p.known and p.opening_hours is None and p.mode == "unknown"


def test_by_schedule_is_unknown_and_not_flagged_as_broken():
    p = parse_hours("согласно расписанию")
    assert not p.known and not p.unparsed


def test_season_dates_without_hours():
    p = parse_hours("1 декабря — 1 марта; сеансы по расписанию")
    assert not p.known and p.season_from == "12-01" and p.season_to == "03-01"


def test_garbage_is_unknown_and_flagged():
    p = parse_hours("уточняйте у администрации")
    assert not p.known and p.unparsed


def test_osm_month_prefix_and_off():
    p = parse_hours("Nov-Mar: Mo-Th 10:00-23:00; Nov-Mar: Fr-Su 10:00-24:00; Apr-Oct off")
    assert w(p, "mon") == [["10:00", "23:00"]] and w(p, "sun") == [["10:00", "24:00"]]


def test_osm_closed_part_skipped():
    p = parse_hours("Mar-Nov closed; Dec-Feb Mo-Su 10:00-22:00")
    assert p.known and w(p, "mon") == [["10:00", "22:00"]]


def test_osm_plain():
    assert w(parse_hours("Mo-Su 08:00-22:00"), "sat") == [["08:00", "22:00"]]


def test_impossible_time_rejected():
    assert not parse_hours("25:00-26:00").known


def test_summary_groups_days():
    p = parse_hours("пн-пт 17.00-21.00; сб-вс 11.00-22.00")
    assert hours_summary_ru(p.opening_hours) == "Пн–Пт 17:00–21:00; Сб–Вс 11:00–22:00"
    assert hours_summary_ru(None) is None


SEED = Path("/Users/maksimvasilenko/Projects/.trainer-crm-state/tasks/TASK-343-assets/seasonal_rinks_seed_2025_26.csv")


def test_every_seed_string_is_parsed_or_explicitly_unknown():
    if not SEED.exists():
        pytest.skip("seed lives outside the repo")
    rows = list(csv.DictReader(SEED.open(encoding="utf-8")))
    known = unknown = 0
    for r in rows:
        p = parse_hours(r["hours"])
        assert not p.unparsed, r["hours"]
        known += p.known
        unknown += not p.known
        if not r["hours"].strip():
            assert not p.known
        if p.mode == "24h":
            assert "круглосут" in r["hours"].lower()
    assert known == 114 - 0 or known >= 110  # 114 известных по ТЗ; 4 "круглосуточно" среди них
    assert known + unknown == 143
