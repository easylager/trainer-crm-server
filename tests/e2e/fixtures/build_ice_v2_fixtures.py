"""TASK-449: фикстуры ice-v2 e2e — реальный вывод shape_schedule, не рукописный JSON.

Запуск: ``python tests/e2e/fixtures/build_ice_v2_fixtures.py`` → tests/e2e/fixtures/ice-v2.json.
Ключ: ``<variant>|<day>|<kind>`` (day: today|tomorrow|weekend|week; kind: skate|ohm|figure).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.application.ice_schedule_v2 import WINDOW_DAYS, shape_schedule

UTC = timezone.utc
MINSK = ZoneInfo("Europe/Minsk")
TODAY = date(2026, 11, 22)  # вс

OUT = Path(__file__).with_name("ice-v2.json")

P = "/photos/"
MINSK_ARENAS = [
    {"id": 38, "name": "Каток на Немиге", "address": "ул. Немига, 8", "slug": "nemiga",
     "photo": {"thumb": P + "arena-38/hero.webp", "card": P + "arena-38/hero.webp"}},
    {"id": 25, "name": "Ледовый дворец", "address": "пр. Победителей, 111", "slug": "ledoviy",
     "photo": {"thumb": P + "arena-25/hero.jpg", "card": P + "arena-25/hero.jpg"}},
    {"id": 11, "name": "Минск-Спортпалас", "address": "пр. Победителей, 4", "slug": "sportpalace",
     "photo": {"thumb": P + "arena-11/hero.webp", "card": P + "arena-11/hero.webp"}},
    {"id": 115, "name": "Чижовка-Арена", "address": "ул. Ташкентская, 7", "slug": "chizh",
     "photo": {"thumb": P + "arena-115/hockey-rink-interior.jpg", "card": P + "arena-115/hockey-rink-interior.jpg"}},
    {"id": 40, "name": "Олимпик Центр", "address": "пр. Дзержинского, 2", "slug": "olimpic",
     "photo": {"thumb": P + "arena-25/hero.jpg", "card": P + "arena-25/hero.jpg"}},
]
PINSK_ARENAS = [
    {"id": 1, "name": "УСК «Волна»", "address": "ул. Завальная, 14", "slug": "volna",
     "photo": {"thumb": P + "mozyr-global-ice/hero.jpg", "card": P + "mozyr-global-ice/hero.jpg"}},
]
ARENA_NAME = {a["id"]: a["name"] for a in MINSK_ARENAS + PINSK_ARENAS}


def row(sid, arena, start, end, *, day=TODAY, kind="public_skate", hall=None):
    """start/end — 'HH:MM' местные (Минск UTC+3); utc вычисляются из них."""
    def utc_of(hhmm):
        h, m = map(int, hhmm.split(":"))
        return datetime(day.year, day.month, day.day, h, m, tzinfo=MINSK).astimezone(UTC)
    return {
        "session_id": sid, "arena_id": arena,
        "arena_name": ARENA_NAME[arena], "kind": kind,
        "starts_at_utc": utc_of(start), "ends_at_utc": utc_of(end),
        "starts_at_local": start, "ends_at_local": end,
        "local_date": day, "price_adult_minor": 1200, "price_rental_minor": 800,
        "currency_code": "BYN", "hall": hall,
    }


TOM = TODAY + timedelta(days=1)
SAT = TODAY + timedelta(days=6)
SUN = TODAY + timedelta(days=7)  # 29.11

# Вечер вс 22.11, 19:30 Минск: 2 идут, 3 ближайших, завтра 6, выходные 5, «с клюшкой», фигурное на выходных.
BASE_ROWS = [
    row(401, 38, "18:30", "20:00"), row(402, 25, "19:00", "20:30"),
    row(403, 11, "20:00", "21:30"), row(404, 115, "20:30", "22:00"), row(405, 40, "21:00", "22:30"),
    row(411, 115, "18:00", "19:45", kind="hockey_practice"),
    row(412, 40, "20:00", "21:30", kind="hockey_practice"),
    row(501, 38, "08:00", "09:30", day=TOM), row(502, 25, "09:00", "10:30", day=TOM),
    row(503, 115, "10:00", "11:30", day=TOM), row(504, 11, "11:00", "12:30", day=TOM),
    row(505, 40, "18:00", "19:30", day=TOM), row(506, 38, "19:00", "20:30", day=TOM),
    row(511, 115, "07:00", "08:30", day=TOM, kind="hockey_practice"),
    row(601, 38, "10:00", "11:30", day=SAT), row(602, 25, "12:00", "13:30", day=SAT),
    row(603, 115, "14:00", "15:30", day=SAT),
    row(604, 11, "10:00", "11:30", day=SUN), row(605, 40, "16:00", "17:30", day=SUN),
    row(611, 11, "09:00", "10:30", day=SAT, kind="figure_free"),
    row(612, 11, "10:00", "11:30", day=SUN, kind="figure_free"),
    row(613, 25, "12:00", "13:30", day=SUN, kind="figure_free"),
    row(701, 38, "10:00", "11:30", day=TODAY + timedelta(days=2)),
    row(702, 25, "10:00", "11:30", day=TODAY + timedelta(days=3)),
    row(703, 115, "10:00", "11:30", day=TODAY + timedelta(days=4)),
]
NIGHT_ROWS = [
    row(410, 25, "09:00", "10:30"), row(411, 38, "10:00", "11:30"), row(412, 115, "10:00", "11:30"),
    row(501, 38, "08:00", "09:30", day=TOM), row(502, 25, "09:00", "10:30", day=TOM),
]
LATE_ROWS = [
    row(501, 38, "08:00", "09:30", day=TOM), row(502, 25, "09:00", "10:30", day=TOM),
    row(503, 115, "10:00", "11:30", day=TOM),
]
# Завтра пусто; ближайший — сб 28.
# Завтра пусто и будни тоже — ближайший лёд «сб, 28».
TM_EMPTY_ROWS = [r for r in BASE_ROWS if r["local_date"] == TODAY or r["local_date"] >= SAT]
PINSK_ROWS = [
    row(401, 1, "18:30", "20:00"), row(403, 1, "20:00", "21:30"),
    row(501, 1, "08:00", "09:30", day=TOM), row(502, 1, "10:00", "11:30", day=TOM),
    row(503, 1, "18:00", "19:30", day=TOM),
    row(504, 1, "12:00", "13:30", day=TODAY + timedelta(days=2)),
    row(505, 1, "19:00", "20:30", day=TODAY + timedelta(days=2)),
    row(506, 1, "10:00", "11:30", day=SAT),
]

# B4: «семейное» и зал — Чижовка с двумя площадками + семейный сеанс на ней.
HALL_ROWS = [
    row(401, 38, "18:30", "20:00"),
    row(413, 115, "19:45", "21:00", kind="family_skate", hall="Конькобежная дорожка"),
    row(414, 115, "21:00", "22:15", hall="Хоккейная площадка"),
    row(403, 11, "20:00", "21:30", hall="Основной лёд"),
    row(501, 38, "08:00", "09:30", day=TOM),
]

MINSK_CITY = {"id": 1, "name": "Минск"}
PINSK_CITY = {"id": 5, "name": "Пинск"}
AT = lambda h, m: datetime(TODAY.year, TODAY.month, TODAY.day, h, m, tzinfo=MINSK).astimezone(UTC)

VARIANTS = {
    "base":           dict(rows=BASE_ROWS, arenas=MINSK_ARENAS, city=MINSK_CITY, now=AT(19, 30)),
    "night":          dict(rows=NIGHT_ROWS, arenas=MINSK_ARENAS, city=MINSK_CITY, now=AT(3, 13)),
    "late":           dict(rows=LATE_ROWS, arenas=MINSK_ARENAS, city=MINSK_CITY, now=AT(23, 10)),
    "tomorrow-empty": dict(rows=TM_EMPTY_ROWS, arenas=MINSK_ARENAS, city=MINSK_CITY, now=AT(19, 30)),
    "onerink":        dict(rows=PINSK_ROWS, arenas=PINSK_ARENAS, city=PINSK_CITY, now=AT(19, 30)),
    "halls":          dict(rows=HALL_ROWS, arenas=MINSK_ARENAS, city=MINSK_CITY, now=AT(19, 30)),
}

# B3: чипы дней — today/tomorrow по имени, дальше ISO-даты; weekend группой.
DAYS = ("today", "tomorrow") + tuple(
    (TODAY + timedelta(days=i)).isoformat() for i in range(2, WINDOW_DAYS)
) + ("weekend", "week")


def main() -> None:
    out = {}
    for name, v in VARIANTS.items():
        for day in DAYS:
            for kind in ("skate", "ohm", "figure"):
                payload = shape_schedule(
                    v["rows"], v["arenas"], city=v["city"],
                    day=day, kind=kind, now=v["now"], today=TODAY,
                )
                out[f"{name}|{day}|{kind}"] = payload
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({len(out)} payloads)")


if __name__ == "__main__":
    main()
