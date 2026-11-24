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
                "price_with_rental": "с прокатом 19\u00a0BYN",
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
    assert block["needs"][3]["line"] == "13 магазинов · 11 открыты сейчас"
    coach = block["needs"][4]
    assert coach["title"] == "Учиться с тренером"
    assert coach["href"] == "trainers?city_id=2", "витрина тренеров, не старый каталог"
    assert coach["line"].startswith("3")


def test_hero_has_fallback_photos_from_rinks_only() -> None:
    block = city_block(_view())
    assert len(block["hero_photos"]) == 2, "каток без фото и магазин — не кандидаты"
    assert block["hero_photo"] == block["hero_photos"][0]
    assert block["hero_photo"]["card"].endswith("arenas/2/card.jpg"), "обложка — самый крупный крытый каток"


def test_live_home_match_takes_the_slot_but_not_over_a_booking_today() -> None:
    live = {"mode": "live", "match": {"id": 10}, "is_home": True, "event_href": "client-match?id=10"}
    slot = now_slot(bookings=None, hockey=live, upcoming=ICE, now=NOW)
    assert slot is not None and slot["kind"] == "kk_before" and slot["hockey"]["mode"] == "live"
    booked = now_slot(bookings=_bookings(_booking()), hockey=live, upcoming=ICE, now=NOW)
    assert booked is not None and booked["kind"] == "booking"


def test_waiting_for_the_result_keeps_the_kk_card_on_the_home_slot() -> None:
    """TASK-359: матч начался, итога нет — карточка игры на главной не исчезает."""
    waiting = {"mode": "waiting", "match": {"id": 11}, "my_pick": {"side": "home"}}
    slot = now_slot(bookings=None, hockey=waiting, upcoming=ICE, now=NOW)
    assert slot is not None and slot["kind"] == "kk_before" and slot["hockey"]["mode"] == "waiting"


def test_city_with_matches_gets_one_hockey_entry_into_the_mini_app_catalog() -> None:
    view = _view()
    view["matches"] = {
        "city_count": 2,
        "first": {"title": "Локомотив Орша — Могилев"},
        "first_word": "сегодня",
        "matches": [{"id": 171}, {"id": 178}],
    }
    block = city_block(view)
    rows = [row for row in block["needs"] if row["key"] == "matches"]
    assert len(rows) == 1, "вход в занятие, а не лента матчей"
    row = rows[0]
    assert row["title"] == "Хоккей"
    assert row["line"] == "2\u00a0матча на неделе · сегодня Локомотив Орша — Могилев"
    assert row["href"] == "client-matches?city=%D0%9C%D0%B8%D0%BD%D1%81%D0%BA"
    assert row["windows"] == []
    assert [r["key"] for r in block["needs"]][:3] == ["skate", "ohm", "matches"], "порядок как на странице города"


def test_city_without_matches_has_no_hockey_entry() -> None:
    for feed in (None, {}):
        view = _view()
        view["matches"] = feed
        assert "matches" not in [row["key"] for row in city_block(view)["needs"]]


"""TASK-445: «Лёд в городе» новой главной — rail сеансов по каткам (ice_rail_window)."""
from src.application.hub_home import ICE_RAIL_ARENAS, ICE_RAIL_TIMES, ice_rail_window


def _rail_row(slug: str, name: str, hhmm: str, sid: int, starts_utc: str) -> dict:
    return {
        "arena_slug": slug,
        "arena_name": name,
        "session_id": sid,
        "starts_at_local": hhmm,
        "local_date": date(2026, 10, 19),
        "price_adult_minor": 1000,
        "currency_code": "BYN",
        "schedule_basis": "live",
        "starts_at_utc": datetime.fromisoformat(starts_utc).replace(tzinfo=timezone.utc),
    }


def _rail_places() -> list[dict]:
    return [
        {"id": 1, "slug": "a", "venue_type": "ice", "photo_variants": {"card": "k1", "thumb": "t1", "hero": "h1"}},
        {"id": 2, "slug": "b", "venue_type": "ice", "photo_variants": {}},
        {"id": 3, "slug": "c", "venue_type": "ice", "photo_variants": {}},
    ]


def test_ice_rail_groups_sessions_by_arena_and_orders_by_first_start() -> None:
    rows = [
        _rail_row("b", "Арена Б", "17:30", 102, "2026-10-19T14:30:00"),
        _rail_row("a", "Арена А", "18:00", 100, "2026-10-19T15:00:00"),
        _rail_row("a", "Арена А", "19:00", 101, "2026-10-19T16:00:00"),
        _rail_row("b", "Арена Б", "20:00", 103, "2026-10-19T17:00:00"),
        _rail_row("b", "Арена Б", "21:00", 104, "2026-10-19T18:00:00"),
        _rail_row("b", "Арена Б", "22:00", 105, "2026-10-19T19:00:00"),
    ]
    out = ice_rail_window(rows, _rail_places(), now=NOW)
    assert [a["arena_id"] for a in out] == [2, 1], "Б ближе (17:30), А — за ним"
    b, a = out
    assert b["name"] == "Арена Б" and b["href"] == "arena?ref=2&s=102"
    assert [t["time"] for t in b["times"]] == ["17:30", "20:00", "21:00"], "не больше трёх чипов"
    assert len(b["times"]) == ICE_RAIL_TIMES
    assert b["times"][1]["href"] == "arena?ref=2&s=103"
    assert a["price"] == "10 BYN"


def test_ice_rail_caps_arenas_and_skips_unknown_slug_gracefully() -> None:
    rows = [
        _rail_row(f"slug{i}", f"Каток {i}", "18:00", 200 + i, "2026-10-19T15:00:00")
        for i in range(ICE_RAIL_ARENAS + 3)
    ]
    places = [{"id": i, "slug": f"slug{i}", "venue_type": "ice", "photo_variants": {}} for i in range(20)]
    out = ice_rail_window(rows, places, now=NOW)
    assert len(out) == ICE_RAIL_ARENAS
    # Каток без строки в places: имя из сеанса, href None, фото пустое.
    rows2 = [_rail_row("ghost", "Призрак", "18:00", 300, "2026-10-19T15:00:00")]
    out2 = ice_rail_window(rows2, [], now=NOW)
    assert out2[0]["name"] == "Призрак" and out2[0]["arena_id"] is None and out2[0]["href"] is None


def test_ice_rail_empty_window_is_empty_list() -> None:
    assert ice_rail_window([], _rail_places(), now=NOW) == []
    assert ice_rail_window(None, None, now=NOW) == []
