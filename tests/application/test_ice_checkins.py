"""TASK-446: чистые функции ice_checkins — сезон, серия, live-загрузка, окна."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.application import ice_checkins as ic


def dt(h, m=0, d=date(2026, 11, 24)):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)


class TestSeasonBounds:
    def test_inside(self):
        assert ic.season_bounds(date(2026, 11, 24)) == (date(2026, 9, 1), date(2027, 8, 31))

    def test_start_day(self):
        assert ic.season_bounds(date(2026, 9, 1)) == (date(2026, 9, 1), date(2027, 8, 31))

    def test_last_day(self):
        assert ic.season_bounds(date(2027, 8, 31)) == (date(2026, 9, 1), date(2027, 8, 31))

    def test_january_belongs_previous(self):
        assert ic.season_bounds(date(2027, 1, 15)) == (date(2026, 9, 1), date(2027, 8, 31))


class TestStreakWeeks:
    def test_empty(self):
        assert ic.streak_weeks([], date(2026, 11, 24)) == 0

    def test_current_week_with_checkin(self):
        # 24.11.2026 — вторник; отметка в понедельник этой недели.
        assert ic.streak_weeks([date(2026, 11, 23)], date(2026, 11, 24)) == 1

    def test_current_week_empty_streak_lives(self):
        # Прошлая и позапрошлая недели с отметками — серия 2 живёт до конца текущей.
        dates = [date(2026, 11, 18), date(2026, 11, 11)]
        assert ic.streak_weeks(dates, date(2026, 11, 24)) == 2

    def test_gap_breaks(self):
        dates = [date(2026, 11, 4), date(2026, 11, 18)]  # пропуск недели 9–15
        assert ic.streak_weeks(dates, date(2026, 11, 24)) == 1

    def test_year_boundary(self):
        # Неделя 29.12–4.01 — одна неделя на стыке года.
        dates = [date(2026, 12, 30), date(2026, 12, 22)]
        assert ic.streak_weeks(dates, date(2027, 1, 2)) == 2

    def test_multiple_checkins_same_week(self):
        dates = [date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 21)]
        assert ic.streak_weeks(dates, date(2026, 11, 24)) == 1


def rep(level, age_min, counts=True):
    return {"load_level": level, "created_at": _NOW - timedelta(minutes=age_min), "counts_for_load": counts}


_NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


class TestLiveLoad:
    def test_empty(self):
        assert ic.live_load([], _NOW) is None

    def test_ignores_uncounted(self):
        assert ic.live_load([rep(1, 5, counts=False)], _NOW) is None

    def test_ignores_stale(self):
        assert ic.live_load([rep(2, 45)], _NOW) is None

    def test_median(self):
        out = ic.live_load([rep(1, 5), rep(2, 4), rep(3, 3)], _NOW)
        assert out["level"] == 2
        assert out["count"] == 3
        assert out["last_min"] == 3

    def test_outlier_dropped(self):
        out = ic.live_load([rep(2, 5), rep(2, 4), rep(2, 3), rep(1, 2), rep(3, 1)], _NOW)
        # медиана других для тройки = 1.5? нет: остальные {2,2,2,1} медиана 2 → 3 отличается на 1
        assert out["count"] == 5

    def test_real_outlier_dropped(self):
        out = ic.live_load([rep(1, 5), rep(1, 4), rep(1, 3), rep(3, 1)], _NOW)
        # у 3 остальные {1,1,1} медиана 1 → diff 2 → выброс
        assert out["level"] == 1
        assert out["count"] == 3

    def test_future_report_ignored(self):
        out = ic.live_load([rep(2, -10)], _NOW)
        assert out is None

    def test_levels_1_and_3_gives_2(self):
        out = ic.live_load([rep(1, 5), rep(3, 4)], _NOW)
        # для 1: остальные {3} медиана 3, diff 2 → 1 выброшен; для 3: остальные {1}, diff 2 → выброшен.
        # Все выброшены → фолбэк к исходным; 1 и 3 есть → 2.
        assert out["level"] == 2
        assert out["count"] == 2


def sess(start=12, end=13, kind="public_skate", status="active"):
    return {
        "starts_at_utc": dt(start), "ends_at_utc": dt(end),
        "kind": kind, "status": status,
    }


class TestIsOngoing:
    def test_inside(self):
        assert ic.is_ongoing(sess(), dt(12, 30)) is True

    def test_early_15min(self):
        assert ic.is_ongoing(sess(), dt(11, 45)) is True
        assert ic.is_ongoing(sess(), dt(11, 44)) is False

    def test_ended(self):
        assert ic.is_ongoing(sess(), dt(13, 0)) is False

    def test_bad_kind(self):
        assert ic.is_ongoing(sess(kind="figure_skating"), dt(12, 30)) is False

    def test_open_ice_ok(self):
        assert ic.is_ongoing(sess(kind="open_ice"), dt(12, 30)) is True

    def test_inactive(self):
        assert ic.is_ongoing(sess(status="expired"), dt(12, 30)) is False


class TestPromptDueAt:
    def test_normal(self):
        # start 12:00 UTC (15:00 Минск), end 14:00 → due 12:20, до конца 100 мин ≥ 30.
        assert ic.prompt_due_at(sess(12, 14)) == dt(12, 20)

    def test_short_session_none(self):
        # start+20 → до конца 25 мин < 30.
        assert ic.prompt_due_at(sess(12, 12, 45)) is None

    def test_window_night(self):
        # due 19:50 UTC = 22:50 Минск — за окном 22:30.
        assert ic.prompt_due_at({
            "starts_at_utc": dt(19, 30), "ends_at_utc": dt(21, 0),
        }) is None
        # due 04:50 UTC = 07:50 Минск — до окна 08:00.
        assert ic.prompt_due_at({
            "starts_at_utc": dt(4, 30), "ends_at_utc": dt(6, 0),
        }) is None

    def test_exact_boundary_ok(self):
        # due ровно 22:30 Минск = 19:30 UTC.
        assert ic.prompt_due_at({"starts_at_utc": dt(19, 10), "ends_at_utc": dt(20, 30)}) == dt(19, 30)


class TestDayGroup:
    def test_groups(self):
        assert ic.day_group(date(2026, 11, 24)) == "weekday"  # вт
        assert ic.day_group(date(2026, 11, 28)) == "sat"
        assert ic.day_group(date(2026, 11, 29)) == "sun"

    def test_monday_weekday(self):
        assert ic.day_group(date(2026, 11, 23)) == "weekday"
