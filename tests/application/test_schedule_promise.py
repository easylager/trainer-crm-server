"""TASK-329 AC4/AC6: schedule_promise — чистая функция обещания по волнам."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.application.schedule_promise import ScheduleWave, schedule_promise, wave_days

MINSK = ZoneInfo("Europe/Minsk")
NONE = {"level": "none", "date": None, "week": None}


def w(day: str, hhmm: str = "15:00", source: str = "parser") -> ScheduleWave:
    hh, mm = (int(x) for x in hhmm.split(":"))
    y, m, d = (int(x) for x in day.split("-"))
    return ScheduleWave(detected_at=datetime(y, m, d, hh, mm, tzinfo=MINSK), source=source)


def promise(waves, today: str, tz="Europe/Minsk"):
    return schedule_promise(waves, date.fromisoformat(today), tz)


# --- мало данных -----------------------------------------------------------------------


def test_no_waves_is_none() -> None:
    assert promise([], "2026-10-24") == NONE


def test_single_wave_is_none() -> None:
    assert promise([w("2026-10-23")], "2026-10-24") == NONE


# --- day ------------------------------------------------------------------------------


FRIDAYS = [w("2026-10-09"), w("2026-10-16"), w("2026-10-23")]


def test_day_three_fridays_promises_next_friday() -> None:
    # сб 24.10 → следующая пятница 30.10 — уже следующая ISO-неделя.
    assert promise(FRIDAYS, "2026-10-24") == {"level": "day", "date": date(2026, 10, 30), "week": "next"}


def test_day_on_the_promised_day_itself() -> None:
    assert promise(FRIDAYS, "2026-10-30") == {"level": "day", "date": date(2026, 10, 30), "week": "this"}


def test_day_promise_missed_is_none_not_week() -> None:
    # пятница 30.10 прошла без волны — обещание сорвано.
    assert promise(FRIDAYS, "2026-10-31") == NONE


def test_day_same_day_as_last_wave_points_a_week_ahead() -> None:
    assert promise(FRIDAYS, "2026-10-23") == {"level": "day", "date": date(2026, 10, 30), "week": "next"}


def test_day_exactly_75_percent() -> None:
    waves = [w("2026-10-02"), w("2026-10-08"), w("2026-10-16"), w("2026-10-23")]  # пт чт пт пт
    assert promise(waves, "2026-10-24")["level"] == "day"


def test_day_below_75_percent_falls_back_to_week() -> None:
    # 3 пт из 5 = 60%; медиана промежутков 6.5 → «на следующей неделе».
    waves = [w("2026-09-25"), w("2026-10-01"), w("2026-10-09"), w("2026-10-15"), w("2026-10-23")]
    assert promise(waves, "2026-10-24") == {"level": "week", "date": None, "week": "next"}


def test_day_two_of_three_is_not_day() -> None:
    waves = [w("2026-10-09"), w("2026-10-15"), w("2026-10-23")]  # пт чт пт
    assert promise(waves, "2026-10-24")["level"] == "week"


def test_day_requires_last_wave_on_the_weekday() -> None:
    waves = [w("2026-10-02"), w("2026-10-09"), w("2026-10-16"), w("2026-10-22")]  # пт пт пт чт
    # 75% пятниц, но последняя — четверг: только неделя, ожидаем 29.10.
    assert promise(waves, "2026-10-24") == {"level": "week", "date": None, "week": "next"}


def test_day_requires_three_iso_weeks() -> None:
    # три пятничные волны, но в двух неделях (две в один день, 12 ч врозь) — не «день».
    waves = [w("2026-10-16", "08:00"), w("2026-10-16", "20:00"), w("2026-10-23")]
    assert promise(waves, "2026-10-24") == NONE


def test_day_sunday_rhythm_promises_this_week_on_saturday() -> None:
    waves = [w("2026-10-04"), w("2026-10-11"), w("2026-10-18")]  # вс вс вс
    assert promise(waves, "2026-10-24") == {"level": "day", "date": date(2026, 10, 25), "week": "this"}


# --- week -----------------------------------------------------------------------------


def test_week_two_mondays_on_saturday_is_next_week() -> None:
    waves = [w("2026-10-12"), w("2026-10-19")]
    assert promise(waves, "2026-10-24") == {"level": "week", "date": None, "week": "next"}


def test_week_sunday_to_monday_switches_to_next_week() -> None:
    waves = [w("2026-10-12"), w("2026-10-19")]  # ожидаем пн 26.10
    assert promise(waves, "2026-10-25")["week"] == "next"  # вс 25.10 — ещё прошлая ISO-неделя
    assert promise(waves, "2026-10-26")["week"] == "this"  # пн 26.10 — та же неделя


def test_week_expected_on_sunday_seen_on_sunday() -> None:
    waves = [w("2026-10-11"), w("2026-10-18")]
    assert promise(waves, "2026-10-25") == {"level": "week", "date": None, "week": "this"}


def test_week_missed_is_none() -> None:
    waves = [w("2026-10-12"), w("2026-10-19")]
    assert promise(waves, "2026-10-27") == NONE


@pytest.mark.parametrize(
    ("first", "level"),
    [
        ("2026-10-18", "week"),  # 5 дней
        ("2026-10-14", "week"),  # 9 дней
        ("2026-10-19", "none"),  # 4 дня
        ("2026-10-13", "none"),  # 10 дней
    ],
)
def test_week_gap_boundaries(first: str, level: str) -> None:
    waves = [w(first), w("2026-10-23")]
    assert promise(waves, "2026-10-24")["level"] == level


# --- none: скользящее окно ------------------------------------------------------------


def test_sliding_window_daily_is_none() -> None:
    waves = [w(f"2026-10-{d:02d}", "00:05") for d in range(10, 25)]
    assert promise(waves, "2026-10-24") == NONE


def test_sliding_window_median_two_days_is_none() -> None:
    waves = [w("2026-10-16"), w("2026-10-18"), w("2026-10-20"), w("2026-10-23")]  # 2,2,3
    assert promise(waves, "2026-10-24") == NONE


def test_sliding_check_beats_day_pattern() -> None:
    # все волны в пятницы трёх недель, но промежутки 7,0,0,0,7 → медиана 0 (≤2) → молчим.
    waves = [
        w("2026-10-02"),
        w("2026-10-09", "00:00"),
        w("2026-10-09", "07:00"),
        w("2026-10-09", "14:00"),
        w("2026-10-09", "21:00"),
        w("2026-10-16"),
    ]
    assert promise(waves, "2026-10-17") == NONE


# --- seed, окно, слияние, пояс --------------------------------------------------------


def test_seed_is_not_counted() -> None:
    waves = [w("2026-10-09", source="seed"), w("2026-10-16"), w("2026-10-23")]
    # с seed было бы 3 пятницы → day; без него — две волны → week.
    assert promise(waves, "2026-10-24") == {"level": "week", "date": None, "week": "next"}


def test_backfill_and_admin_waves_count() -> None:
    waves = [w("2026-10-09", source="backfill"), w("2026-10-16", source="admin"), w("2026-10-23")]
    assert promise(waves, "2026-10-24")["level"] == "day"


def test_window_is_42_days_inclusive() -> None:
    waves = [w("2026-09-11"), w("2026-10-09"), w("2026-10-16")]  # пт пт пт
    # чт 22.10: окно с 11.09 — три волны → день (пт 23.10).
    assert promise(waves, "2026-10-22") == {"level": "day", "date": date(2026, 10, 23), "week": "this"}
    # пт 23.10: окно с 12.09 — 11.09 выпала, две волны → неделя.
    assert promise(waves, "2026-10-23") == {"level": "week", "date": None, "week": "this"}


def test_waves_within_six_hours_merge() -> None:
    waves = [
        w("2026-10-09", "15:00"),
        w("2026-10-09", "16:00"),
        w("2026-10-16", "15:00"),
        w("2026-10-16", "20:59"),
        w("2026-10-23", "15:00"),
    ]
    assert promise(waves, "2026-10-24")["level"] == "day"
    assert len(wave_days(waves, today=date(2026, 10, 24), tz="Europe/Minsk")) == 3


def test_future_waves_are_ignored() -> None:
    waves = FRIDAYS + [w("2026-10-26")]
    assert promise(waves, "2026-10-24")["level"] == "day"


def test_local_weekday_uses_arena_timezone() -> None:
    # 22:30 UTC четверга = 01:30 пятницы в Минске.
    waves = [
        ScheduleWave(detected_at=datetime(2026, 10, d, 22, 30, tzinfo=timezone.utc), source="parser")
        for d in (8, 15, 22)
    ]
    assert promise(waves, "2026-10-24") == {"level": "day", "date": date(2026, 10, 30), "week": "next"}
    assert promise(waves, "2026-10-24", tz="UTC") == {"level": "day", "date": date(2026, 10, 29), "week": "next"}


def test_naive_datetimes_are_utc_and_unknown_tz_falls_back() -> None:
    waves = [ScheduleWave(detected_at=datetime(2026, 10, d, 12, 0), source="parser") for d in (9, 16, 23)]
    assert promise(waves, "2026-10-24", tz=None)["level"] == "day"
    assert promise(waves, "2026-10-24", tz="Not/AZone")["level"] == "day"


def test_random_inputs_keep_the_contract() -> None:
    rng = random.Random(329)
    today = date(2026, 10, 24)
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    seen = set()
    for _ in range(5000):
        waves = [
            ScheduleWave(
                detected_at=base + timedelta(minutes=rng.randrange(0, 60 * 24 * 60)),
                source=rng.choice(["parser", "admin", "backfill", "seed"]),
            )
            for _ in range(rng.randrange(0, 9))
        ]
        result = schedule_promise(waves, today, "Europe/Minsk")
        seen.add(result["level"])
        assert set(result) == {"level", "date", "week"}
        if result["level"] == "none":
            assert result == NONE
        elif result["level"] == "day":
            assert today <= result["date"] <= today + timedelta(days=7)
            assert result["week"] in {"this", "next"}
        else:
            assert result["level"] == "week" and result["date"] is None
            assert result["week"] in {"this", "next"}
    assert "none" in seen and "week" in seen
