"""TASK-329 AC4/AC6: schedule_habit — чистая функция «обычно выкладывает по …»."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.application.schedule_habit import ScheduleWave, schedule_habit, wave_days, waves_in_window

MINSK = ZoneInfo("Europe/Minsk")
NONE = {"level": "none", "weekday": None}
WEEK = {"level": "week", "weekday": None}
FRI = 4


def w(day: str, hhmm: str = "15:00", source: str = "parser") -> ScheduleWave:
    hh, mm = (int(x) for x in hhmm.split(":"))
    y, m, d = (int(x) for x in day.split("-"))
    return ScheduleWave(detected_at=datetime(y, m, d, hh, mm, tzinfo=MINSK), source=source)


def habit(waves, tz="Europe/Minsk"):
    return schedule_habit(waves, tz)


# --- мало данных ----------------------------------------------------------------------


def test_no_waves_is_none() -> None:
    assert habit([]) == NONE


def test_single_wave_is_none() -> None:
    assert habit([w("2026-10-23")]) == NONE


# --- day ------------------------------------------------------------------------------


def test_day_three_fridays() -> None:
    assert habit([w("2026-10-09"), w("2026-10-16"), w("2026-10-23")]) == {"level": "day", "weekday": FRI}


def test_day_exactly_75_percent() -> None:
    waves = [w("2026-10-02"), w("2026-10-08"), w("2026-10-16"), w("2026-10-23")]  # пт чт пт пт
    assert habit(waves) == {"level": "day", "weekday": FRI}


def test_day_last_wave_off_the_weekday_still_counts() -> None:
    waves = [w("2026-10-02"), w("2026-10-09"), w("2026-10-16"), w("2026-10-22")]  # пт пт пт чт
    assert habit(waves) == {"level": "day", "weekday": FRI}


def test_day_below_75_percent_falls_back_to_week() -> None:
    # 3 пт из 5 = 60%; медиана промежутков 6.5.
    waves = [w("2026-09-25"), w("2026-10-01"), w("2026-10-09"), w("2026-10-15"), w("2026-10-23")]
    assert habit(waves) == WEEK


def test_day_two_of_three_is_week() -> None:
    assert habit([w("2026-10-09"), w("2026-10-15"), w("2026-10-23")]) == WEEK  # пт чт пт


def test_day_requires_three_iso_weeks() -> None:
    # три пятничные волны, но в двух неделях (две в один день, 12 ч врозь); медиана 3.5.
    waves = [w("2026-10-16", "08:00"), w("2026-10-16", "20:00"), w("2026-10-23")]
    assert habit(waves) == NONE


def test_day_iso_weeks_split_on_monday() -> None:
    # вс 11.10 и пн 12.10 — разные ISO-недели; три воскресенья + понедельник = 75% вс.
    waves = [w("2026-10-04"), w("2026-10-11"), w("2026-10-12", "23:00"), w("2026-10-18")]
    # промежутки 7,1,6 → медиана 6, не скользящее окно
    assert habit(waves) == {"level": "day", "weekday": 6}


def test_day_sunday_weekday_is_six() -> None:
    assert habit([w("2026-10-04"), w("2026-10-11"), w("2026-10-18")]) == {"level": "day", "weekday": 6}


# --- week -----------------------------------------------------------------------------


def test_week_two_mondays() -> None:
    assert habit([w("2026-10-12"), w("2026-10-19")]) == WEEK


@pytest.mark.parametrize(
    ("first", "expected"),
    [
        ("2026-10-18", WEEK),  # 5 дней
        ("2026-10-14", WEEK),  # 9 дней
        ("2026-10-19", NONE),  # 4 дня
        ("2026-10-13", NONE),  # 10 дней
    ],
)
def test_week_gap_boundaries(first: str, expected: dict) -> None:
    assert habit([w(first), w("2026-10-23")]) == expected


# --- none: скользящее окно ------------------------------------------------------------


def test_sliding_window_daily_is_none() -> None:
    assert habit([w(f"2026-10-{d:02d}", "00:05") for d in range(10, 25)]) == NONE


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (["2026-10-16", "2026-10-18", "2026-10-20", "2026-10-23"], NONE),  # 2,2,3 → медиана 2
        (["2026-10-14", "2026-10-17", "2026-10-20"], NONE),  # 3,3 → медиана 3: не скользящее, но и не неделя
    ],
)
def test_sliding_window_boundary(days: list[str], expected: dict) -> None:
    assert habit([w(d) for d in days]) == expected


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
    assert habit(waves) == NONE


# --- seed, слияние, пояс --------------------------------------------------------------


def test_seed_is_not_counted() -> None:
    waves = [w("2026-10-09", source="seed"), w("2026-10-16"), w("2026-10-23")]
    # с seed было бы 3 пятницы → day; без него — две волны → week.
    assert habit(waves) == WEEK


def test_backfill_and_admin_waves_count() -> None:
    waves = [w("2026-10-09", source="backfill"), w("2026-10-16", source="admin"), w("2026-10-23")]
    assert habit(waves) == {"level": "day", "weekday": FRI}


def test_waves_within_six_hours_merge() -> None:
    waves = [
        w("2026-10-09", "15:00"),
        w("2026-10-09", "16:00"),
        w("2026-10-16", "15:00"),
        w("2026-10-16", "20:59"),
        w("2026-10-23", "15:00"),
    ]
    assert habit(waves) == {"level": "day", "weekday": FRI}
    assert len(wave_days(waves, "Europe/Minsk")) == 3


def test_local_weekday_uses_arena_timezone() -> None:
    # 22:30 UTC четверга = 01:30 пятницы в Минске.
    waves = [
        ScheduleWave(detected_at=datetime(2026, 10, d, 22, 30, tzinfo=timezone.utc), source="parser")
        for d in (8, 15, 22)
    ]
    assert habit(waves) == {"level": "day", "weekday": FRI}
    assert habit(waves, tz="UTC") == {"level": "day", "weekday": 3}


def test_naive_datetimes_are_utc_and_unknown_tz_falls_back() -> None:
    waves = [ScheduleWave(detected_at=datetime(2026, 10, d, 12, 0), source="parser") for d in (9, 16, 23)]
    assert habit(waves, tz=None)["level"] == "day"
    assert habit(waves, tz="Not/AZone")["level"] == "day"


# --- окно 42 дня ----------------------------------------------------------------------


def test_window_is_42_days_up_to_now() -> None:
    now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    edge = ScheduleWave(detected_at=now - timedelta(days=42), source="parser")
    old = ScheduleWave(detected_at=now - timedelta(days=42, seconds=1), source="parser")
    future = ScheduleWave(detected_at=now + timedelta(seconds=1), source="parser")
    current = ScheduleWave(detected_at=now, source="parser")
    assert waves_in_window([old, edge, current, future], now=now) == [edge, current]
    naive_now = datetime(2026, 10, 24, 12, 0)
    assert waves_in_window([edge], now=naive_now) == [edge]


def test_window_drops_old_waves_from_habit() -> None:
    waves = [w("2026-09-11"), w("2026-10-09"), w("2026-10-16")]  # пт пт пт
    inside = datetime(2026, 10, 23, 0, 0, tzinfo=MINSK)  # 11.09 15:00 ещё в окне
    later = datetime(2026, 10, 23, 16, 0, tzinfo=MINSK)  # уже нет
    assert habit(waves_in_window(waves, now=inside)) == {"level": "day", "weekday": FRI}
    assert habit(waves_in_window(waves, now=later)) == WEEK


# --- контракт на случайных данных -----------------------------------------------------


def test_random_inputs_keep_the_contract() -> None:
    rng = random.Random(329)
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
        result = habit(waves)
        seen.add(result["level"])
        assert set(result) == {"level", "weekday"}
        if result["level"] == "day":
            assert result["weekday"] in range(7)
        else:
            assert result["weekday"] is None and result["level"] in {"week", "none"}
    assert seen == {"day", "week", "none"}
