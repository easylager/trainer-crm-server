"""TASK-447: чистые билдеры home_s2 — неделя, следующий лёд, один каток, nearby."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.application.city_style_b import VARIANT_MANY, VARIANT_ONE
from src.application.home_s2 import (
    build_nearby,
    build_next_ice,
    build_one_rink,
    build_week,
    is_small_city,
)

NOW = datetime(2026, 11, 22, 16, 30, tzinfo=timezone.utc)  # вс 19:30 Минск
TODAY = date(2026, 11, 22)

PLACES_ONE = [
    {"id": 11, "slug": "volna", "name": 'УСК «Волна»', "venue_type": "ice",
     "photo_variants": {"card": {"k": "1"}, "thumb": {"k": "2"}, "hero": {"k": "3"}},
     "yandex_url": "https://yandex.ru/maps/?volna"},
]
PLACES_TWO = PLACES_ONE + [
    {"id": 12, "slug": "ledoviy", "name": "Ледовый дворец", "venue_type": "ice",
     "photo_variants": {"card": {"k": "4"}}},
]


def row(session_id, hhmm, *, day=TODAY, slug="volna", start_utc=None, adult=440, rental=420, end="20:30"):
    return {
        "session_id": session_id,
        "arena_slug": slug,
        "arena_name": 'УСК «Волна»' if slug == "volna" else "Ледовый дворец",
        "starts_at_local": hhmm,
        "ends_at_local": end,
        "local_date": day,
        "starts_at_utc": start_utc if start_utc is not None else NOW + timedelta(hours=2),
        "price_adult_minor": adult,
        "price_rental_minor": rental,
        "currency_code": "BYN",
        "basis_label": "Массовое катание",
    }


class TestSmallCity:
    def test_variant_one_always_small(self):
        assert is_small_city(VARIANT_ONE, 200) is True

    def test_many_small_by_count(self):
        assert is_small_city(VARIANT_MANY, 40) is True
        assert is_small_city(VARIANT_MANY, 41) is False


class TestWeek:
    def test_seven_days_labels_and_sub(self):
        week = build_week([], PLACES_ONE, today=TODAY, now=NOW)
        assert len(week) == 7
        assert week[0]["label"] == "Сегодня" and week[0]["sub"] == "22"
        assert week[1]["label"] == "Завтра" and week[1]["sub"] == "23"
        assert week[2]["label"] == "Вт" and week[6]["sub"] == "28"

    def test_grouping_past_and_cap(self):
        rows = [row(1, "18:00", start_utc=NOW - timedelta(hours=1))]  # уже начался
        rows += [row(100 + i, f"{10 + i}:00") for i in range(8)]  # 8 завтра? нет — сегодня
        for r in rows[1:]:
            r["local_date"] = TODAY + timedelta(days=1)
        week = build_week(rows, PLACES_TWO, today=TODAY, now=NOW)
        today_times = week[0]["times"]
        assert len(today_times) == 1
        assert today_times[0]["past"] is True
        assert today_times[0]["arena_name"] == 'УСК «Волна»'  # multi-rink — имя есть
        assert week[1]["times"][0]["past"] is False
        assert len(week[1]["times"]) == 6  # cap

    def test_arena_name_hidden_single_rink(self):
        week = build_week([row(1, "19:00")], PLACES_ONE, today=TODAY, now=NOW)
        assert "arena_name" not in week[0]["times"][0]

    def test_rows_outside_week_ignored(self):
        week = build_week([row(1, "19:00", day=TODAY + timedelta(days=8))], PLACES_ONE, today=TODAY, now=NOW)
        assert all(not d["times"] for d in week)


class TestNextIce:
    def test_first_future(self):
        nxt = build_next_ice([row(1, "12:00", start_utc=NOW - timedelta(hours=3)),
                            row(2, "20:15", day=TODAY + timedelta(days=6), start_utc=NOW + timedelta(days=6))],
                           PLACES_ONE, today=TODAY, now=NOW)
        assert nxt["date_label"] == "сб, 28" and nxt["time"] == "20:15"
        assert nxt["arena_id"] == 11 and nxt["href"] == "arena?ref=11&s=2"

    def test_none_means_offseason(self):
        assert build_next_ice([], PLACES_ONE, today=TODAY, now=NOW) is None


class TestOneRink:
    def test_card_prices_and_later(self):
        one = build_one_rink(
            [row(1, "19:10", start_utc=NOW + timedelta(minutes=100)),
             row(2, "21:00", start_utc=NOW + timedelta(hours=4))],
            PLACES_ONE, today=TODAY, now=NOW,
            invite_link=lambda a, s: f"https://t.me/x?start={a}_{s}",
        )
        assert one["time"] == "19:10" and one["end"] == "20:30"
        assert one["minutes_until"] == 100
        assert one["day_label"] == "Сегодня"
        assert one["later_today"] == "21:00"
        assert one["prices"] == [
            {"value": "4,40 BYN", "label": "взрослый"},
            {"value": "8,60 BYN", "label": "с прокатом"},
        ]
        assert one["invite_url"] == "https://t.me/x?start=11_1"
        assert one["map_link"] == "https://yandex.ru/maps/?volna"

    def test_no_upcoming(self):
        assert build_one_rink([row(1, "10:00", start_utc=NOW - timedelta(hours=1))],
                              PLACES_ONE, today=TODAY, now=NOW) is None

    def test_next_week_not_shown(self):
        assert build_one_rink([row(1, "10:00", day=TODAY + timedelta(days=8),
                                   start_utc=NOW + timedelta(days=8))],
                              PLACES_ONE, today=TODAY, now=NOW) is None

    def test_adult_only_price(self):
        one = build_one_rink([row(1, "19:10", rental=None)], PLACES_ONE, today=TODAY, now=NOW)
        assert one["prices"] == [{"value": "4,40 BYN", "label": "взрослый"}]


class TestNearby:
    def test_mapping(self):
        out = build_nearby([
            {"name": "Слуцк", "photo_url": "ph", "when": "tomorrow", "time": "12:00",
             "distance": "96 км", "rink_count": 1},
            {"name": " ", "photo_url": "x"},
        ])
        assert out == [{
            "name": "Слуцк", "photo": "ph", "sub": "завтра · 12:00 · 96 км",
            "rink_count": 1, "href": None,
        }]
