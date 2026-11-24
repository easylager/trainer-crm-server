"""TASK-449: чистый шейпинг ice_schedule_v2 — заголовок, «идёт сейчас», группы, «завтра с утра»."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.application.ice_schedule_v2 import (
    resolve_day,
    shape_schedule,
    weekend_days,
)

UTC = timezone.utc
# «Сейчас» — вс 22.11.2026 18:40 Минск = 15:40 UTC.
TODAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 15, 40, tzinfo=UTC)
TOMORROW = TODAY + timedelta(days=1)

CITY = {"id": 1, "name": "Минск"}
ARENAS = [
    {"id": 11, "name": "Каток на Немиге", "slug": "nemiga",
     "photo": {"thumb": "/p/t.webp", "card": "/p/c.webp"}},
    {"id": 12, "name": "Ледовый дворец", "slug": "ledoviy",
     "photo": {"thumb": "/p/t2.webp", "card": "/p/c2.webp"}},
]


def row(sid, start_local, end_local, *, day=TODAY, arena=11, kind="public_skate",
        start_utc=None, end_utc=None, adult=1200, rental=800):
    """start_local/end_local — 'HH:MM' местные; utc — реальные datetime (Минск = UTC+3)."""
    if start_utc is None:
        h, m = map(int, start_local.split(":"))
        start_utc = datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfoMinsk()) .astimezone(UTC)
    if end_utc is None:
        h, m = map(int, end_local.split(":"))
        end_utc = datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfoMinsk()).astimezone(UTC)
    return {
        "session_id": sid, "arena_id": arena,
        "arena_name": "Каток на Немиге" if arena == 11 else "Ледовый дворец",
        "arena_slug": "x", "kind": kind,
        "starts_at_utc": start_utc, "ends_at_utc": end_utc,
        "starts_at_local": start_local, "ends_at_local": end_local,
        "local_date": day, "price_adult_minor": adult, "price_rental_minor": rental,
        "currency_code": "BYN",
    }


def ZoneInfoMinsk():
    from zoneinfo import ZoneInfo
    return ZoneInfo("Europe/Minsk")


def shape(rows, *, day="today", kind="skate", now=NOW, arenas=ARENAS):
    return shape_schedule(rows, arenas, city=CITY, day=day, kind=kind, now=now, today=TODAY)


def test_today_evening_ongoing_and_upcoming():
    rows = [
        row(1, "18:00", "19:15", arena=11),   # идёт, ещё 35 мин
        row(2, "18:00", "19:30", arena=12),   # идёт, ещё 50 мин
        row(3, "19:00", "20:00", arena=12),   # будущий
        row(4, "21:00", "22:15", arena=11),   # будущий
        row(5, "08:00", "09:30", day=TOMORROW, arena=12),  # завтра утром
        row(6, "10:00", "11:15", day=TOMORROW, arena=11),
    ]
    out = shape(rows)
    assert [r["session_id"] for r in out["ongoing"]] == [1, 2]
    assert out["ongoing"][0]["minutes_left"] == 35
    assert out["now_line"] == "Сейчас 18:40"
    assert [r["session_id"] for r in out["upcoming"]] == [3, 4]
    assert out["title"]["main"] == "4 сеанса массового"
    sub = "".join(p["text"] for p in out["title"]["sub_parts"])
    assert "из 4 сегодня" in sub and "на 2 катках" in sub
    assert out["title"]["sub_parts"][-1] == {"text": "2 идут сейчас", "tone": "live"}
    tm = out["tomorrow_morning"]
    assert tm and tm["total"] == 2 and len(tm["rows"]) == 2 and tm["href_day"] == "tomorrow"
    assert tm["label"] == "пн, 23 ноября"
    kinds = {k["key"]: k for k in out["kinds"]}
    assert kinds["skate"]["count"] == 4 and kinds["ohm"]["count"] == 0
    days = {d["key"]: d for d in out["days"]}
    assert days["today"]["count"] == 4 and days["tomorrow"]["count"] == 2


def test_ongoing_dropped_when_less_than_15_minutes_left():
    # До конца «идущего» сеанса 10 минут — из списка уходит совсем.
    rows = [row(1, "18:00", "18:50", arena=11), row(2, "19:30", "20:30", arena=11)]
    out = shape(rows)
    assert out["ongoing"] == []
    assert [r["session_id"] for r in out["upcoming"]] == [2]


def test_night_sub_and_now_line_first():
    # 03:13 ночи, сеансов ещё не было — «ближайший в 10:00, через 7 ч».
    now = datetime(2026, 11, 22, 0, 13, tzinfo=UTC)
    rows = [row(1, "10:00", "11:30", arena=11), row(2, "12:00", "13:00", arena=12)]
    out = shape(rows, now=now)
    assert out["ongoing"] == []
    assert out["now_line"] == "Сейчас 03:13"
    sub = "".join(p["text"] for p in out["title"]["sub_parts"])
    assert "ближайший в 10:00" in sub and "через" in sub
    assert out["title"]["main"] == "2 сеанса массового"


def test_late_ice_ended_today():
    # 23:10: сегодня пусто, завтра 2 сеанса — «Сегодня лёд закончился».
    now = datetime(2026, 11, 22, 20, 10, tzinfo=UTC)
    rows = [row(1, "08:00", "09:30", day=TOMORROW, arena=12)]
    out = shape(rows, now=now)
    assert out["title"]["main"] == "Сегодня лёд закончился"
    sub = out["title"]["sub_parts"][0]["text"]
    assert "завтра 1 сеанс" in sub and "первый в 08:00" in sub
    assert out["now_line"] is None
    assert out["tomorrow_morning"] and out["tomorrow_morning"]["total"] == 1


def test_tomorrow_empty_gives_next_ice():
    rows = [row(1, "19:00", "20:00", arena=11),
            row(2, "09:00", "10:00", day=TODAY + timedelta(days=5), arena=11)]
    out = shape(rows)
    assert out["tomorrow_morning"] is None
    assert out["next_ice"]["date"] == (TODAY + timedelta(days=5)).isoformat()
    assert out["next_ice"]["label"] == "пт, 27"


def test_kind_filter_and_empty_kind_counts():
    rows = [
        row(1, "19:00", "20:00", kind="hockey_practice"),
        row(2, "20:00", "21:00", kind="public_skate"),
    ]
    out = shape(rows, kind="ohm")
    assert len(out["upcoming"]) == 1 and out["upcoming"][0]["kind"] == "ohm"
    assert out["title"]["main"] == "1 сеанс с клюшкой"
    kinds = {k["key"]: k for k in out["kinds"]}
    assert kinds["figure"]["count"] == 0 and kinds["skate"]["week_count"] == 1


def test_weekend_grouping():
    sat, sun = weekend_days(TODAY)  # вс 22.11 → сб 28 + вс 29
    rows = [
        row(1, "10:00", "11:00", day=sat, arena=11),
        row(2, "12:00", "13:00", day=sat, arena=12),
        row(3, "09:00", "10:00", day=sun, arena=11),
    ]
    out = shape(rows, day="weekend")
    assert [g["date"] for g in out["groups"]] == [sat.isoformat(), sun.isoformat()]
    assert out["groups"][0]["label"] == "сб, 28"
    assert len(out["groups"][0]["rows"]) == 2
    assert out["now_line"] is None and out["ongoing"] == []


def test_week_grouping_and_title():
    rows = [row(1, "10:00", "11:00", day=TODAY + timedelta(i + 1)) for i in range(3)]
    out = shape(rows, day="week")
    assert len(out["groups"]) == 3
    assert out["title"]["main"] == "3 сеанса массового"
    days = {d["key"]: d for d in out["days"]}
    assert days["week"]["count"] == 3


def test_title_plurals():
    for n, word in ((1, "сеанс"), (3, "сеанса"), (16, "сеансов")):
        rows = [row(100 + i, f"{(18 + i) % 24:02d}:00", f"{(19 + i) % 24:02d}:00", kind="figure_free") for i in range(n)]
        out = shape(rows, kind="figure")
        assert out["title"]["main"] == f"{n} {word} фигурного"


def test_row_shape_and_price_line():
    out = shape([row(7, "19:00", "20:15", arena=11)])
    r = out["upcoming"][0]
    assert r["session_id"] == 7 and r["arena_id"] == 11
    assert r["time"] == "19:00" and r["end"] == "20:15"
    assert r["price_line"] == "до 20:15 · 12 BYN · прокат 8"
    assert r["href"] == "arena?ref=11&s=7"
    assert r["photo"]["thumb"] == "/p/t.webp"


def test_one_rink_and_arenas_for_search():
    out = shape([row(1, "19:00", "20:00")], arenas=ARENAS[:1])
    assert out["one_rink"] is True
    assert out["arenas"] == [{"id": 11, "name": "Каток на Немиге"}]
    assert out["city"]["name_in"] == "Минске"


def test_resolve_day():
    assert resolve_day("today", TODAY) == [TODAY]
    assert resolve_day("tomorrow", TODAY) == [TOMORROW]
    assert resolve_day("week", TODAY)[-1] == TODAY + timedelta(days=6)
    assert resolve_day("2026-11-28", TODAY) == [date(2026, 11, 28)]
    assert resolve_day("nonsense", TODAY) is None


def test_sub_nearest_soon_is_live():
    # 18:40, ближайший в 19:00 (20 мин) — зелёная часть «ближайший …».
    rows = [row(1, "19:00", "20:00", arena=11), row(2, "21:00", "22:00", arena=12)]
    out = shape(rows)
    parts = out["title"]["sub_parts"]
    assert parts[-1] == {"text": "ближайший в 19:00, через 20 мин", "tone": "live"}
    assert "из 2 сегодня" in parts[0]["text"]


def test_sub_nearest_far_is_muted():
    # До ближайшего 2ч20м: вся строка серая, но с «из N сегодня».
    rows = [row(1, "21:00", "22:00", arena=11)]
    out = shape(rows)
    parts = out["title"]["sub_parts"]
    assert len(parts) == 1 and "tone" not in parts[0]
    assert "из 1 сегодня" in parts[0]["text"] and "ближайший в 21:00" in parts[0]["text"]


def test_sub_one_rink_wording():
    out = shape([row(1, "19:00", "20:00")], arenas=ARENAS[:1])
    sub = "".join(p["text"] for p in out["title"]["sub_parts"])
    assert "на одном катке" in sub


def test_one_rink_card_and_week():
    rows = [
        row(1, "19:00", "20:00"),
        row(2, "10:00", "11:00", day=TOMORROW),
        row(3, "12:00", "13:00", day=TODAY + timedelta(days=6)),
    ]
    out = shape(rows, arenas=ARENAS[:1])
    assert out["rink"]["id"] == 11 and out["rink"]["href"] == "arena?ref=11"
    assert [w["label"] for w in out["week"]] == ["Завтра", "Сб"]
    assert out["week"][0]["times"][0]["time"] == "10:00"
    # Сегодняшний день в «На неделе» не попадает.
    assert all(w["date"] != TODAY.isoformat() for w in out["week"])
