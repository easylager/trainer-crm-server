"""TASK-303: главная клиента — слот «сейчас» и блок города."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from src.application.hub_home import city_block, now_slot

# 19.10.2026 15:00 UTC = 18:00 в Минске.
NOW = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)
ICE = [{"time": "18:15", "place": "ТЦ Замок"}, {"time": "18:30", "place": "Чижовка-арена"}]
KK_BEFORE = {"mode": "before", "match": {"id": 9}}
KK_RESULT = {"mode": "result", "match": {"id": 8}, "points": 5}


def _bookings(*items: dict, day: str = "2026-10-19") -> dict:
    return {"days": [{"date": day, "bookings": list(items)}]}


def _booking(start: str = "18:30", end: str = "19:15", status: str = "confirmed") -> dict:
    return {"id": 1, "start_time": start, "end_time": end, "status": status, "trainer_name": "Максим"}


def test_booking_today_beats_everything() -> None:
    slot = now_slot(bookings=_bookings(_booking()), hockey=KK_RESULT, upcoming=ICE, now=NOW)
    assert slot is not None and slot["kind"] == "booking"
    assert slot["minutes_until"] == 30


def test_finished_or_cancelled_booking_gives_way_to_the_game() -> None:
    over = _bookings(_booking(start="16:00", end="17:00"), _booking(status="cancelled"))
    slot = now_slot(bookings=over, hockey=KK_RESULT, upcoming=ICE, now=NOW)
    assert slot is not None and slot["kind"] == "kk_result"
    tomorrow = _bookings(_booking(), day="2026-10-20")
    slot = now_slot(bookings=tomorrow, hockey=KK_BEFORE, upcoming=ICE, now=NOW)
    assert slot is not None and slot["kind"] == "kk_before"


def test_without_city_the_game_waits_for_the_city() -> None:
    assert now_slot(bookings=None, hockey=KK_BEFORE, upcoming=[], now=NOW, has_city=False) is None
    booked = now_slot(bookings=_bookings(_booking()), hockey=KK_BEFORE, upcoming=[], now=NOW, has_city=False)
    assert booked is not None and booked["kind"] == "booking", "своя запись важнее города"


def test_nearest_ice_when_nothing_else_and_none_without_ice() -> None:
    slot = now_slot(bookings=None, hockey={"mode": None}, upcoming=ICE, now=NOW)
    assert slot == {"kind": "ice", "session": ICE[0]}
    assert now_slot(bookings=None, hockey=None, upcoming=[], now=NOW) is None


def _view() -> dict:
    return {
        "city": {"id": 2, "name": "Минск"},
        "today": date(2026, 10, 19),
        "skate_counts": {"today": 8, "tomorrow": 20, "weekend": 52, "all": 144},
        "ohm_counts": {"today": 0, "tomorrow": 4, "weekend": 1, "all": 9},
        "hot_skate": "today",
        "hot_ohm": "tomorrow",
        "rink_count": 10,
        "ohm_arena_count": 2,
        "next_ohm": {"starts_at_local": time(10, 0), "local_date": date(2026, 10, 20)},
        "service_count": 12,
        "service_open": [{}] * 8,
        "shop_count": 13,
        "shops_open": [{}] * 11,
        "trainer_count": 3,
        "places": [
            {
                "id": 3,
                "slug": "tts-zamok",
                "venue_type": "ice",
                "photo_hero": "x",
                "photo_width": 1920,
                "photo_variants": {"card": "arenas/3/card.jpg"},
            },
            {"id": 9, "slug": "no-photo", "venue_type": "ice", "photo_hero": None, "photo_variants": {}},
            {
                "id": 2,
                "slug": "minsk-arena",
                "venue_type": "ice",
                "photo_hero": "y",
                "photo_width": 3744,
                "photo_variants": {"card": "arenas/2/card.jpg"},
            },
            {
                "id": 7,
                "slug": "shop",
                "venue_type": "shop",
                "photo_hero": "z",
                "photo_variants": {"card": "arenas/7/card.jpg"},
            },
        ],
        "upcoming": [
            {
                "arena_slug": "tts-zamok",
                "arena_name": "ТЦ Замок",
                "session_id": 24789,
                "starts_at_local": time(18, 15),
                "local_date": date(2026, 10, 19),
                "price_adult_minor": 1000,
                "currency_code": "BYN",
                "price_with_rental": "с прокатом 19 BYN",
            }
        ],
    }


def test_city_block_matches_the_city_page_with_mini_app_links() -> None:
    block = city_block(_view())
    assert block["name"] == "Минск"
    assert block["counts_line"] == "Сегодня ещё 8\u00a0сеансов, завтра — 20"
    first = block["upcoming"][0]
    assert first["badge"] == "18:15"
    assert first["place"] == "ТЦ Замок"
    assert first["href"] == "arena?ref=3&s=24789"
    keys = [row["key"] for row in block["needs"]]
    assert keys == ["skate", "ohm", "service", "shop", "coach"]
    skate = block["needs"][0]
    assert [w["count"] for w in skate["windows"]] == [8, 20, 52]
    assert skate["windows"][0]["href"] == "ice?city_id=2&when=today&intent=skate"
    ohm = block["needs"][1]
    assert ohm["line"] == "ОХМ на 2 катках · ближайший завтра в 10:00"
    assert ohm["windows"][0]["href"] is None, "ноль — не ссылка"
    assert block["needs"][2]["line"] == "12 мест · 8 открыты сейчас"


def test_hero_has_fallback_photos_from_rinks_only() -> None:
    block = city_block(_view())
    assert len(block["hero_photos"]) == 2, "каток без фото и магазин — не кандидаты"
    assert block["hero_photo"] == block["hero_photos"][0]
    assert block["hero_photo"]["card"].endswith("arenas/2/card.jpg"), "обложка — самый крупный крытый каток"
