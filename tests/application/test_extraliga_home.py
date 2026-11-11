from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application import extraliga_home
from src.application.hub_home import now_slot
from src.shared.config import Settings

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def test_now_slot_feed_orders_city_matches_dinamo_then_more():
    hockey = {"mode": "before", "match": {"id": 1}}
    feed = {"matches": [{"kind": "extraliga", "id": 7}], "week_count": 17, "all_href": "client-matches"}
    out = now_slot(bookings=None, hockey=hockey, upcoming=[], now=NOW, extraliga=feed)
    assert out["kind"] == "feed"
    assert [i["kind"] for i in out["items"]] == ["extraliga", "kk_before", "more"]
    assert out["items"][-1]["count"] == 17


def test_now_slot_feed_keeps_all_matches_entry_when_nothing_this_week():
    hockey = {"mode": "before", "match": {"id": 1, "starts_at": "2026-11-10T16:00:00+00:00"}}
    feed = {"matches": [{"kind": "extraliga", "id": 7}], "week_count": 0, "all_href": "client-matches?city=2"}
    out = now_slot(bookings=None, hockey=hockey, upcoming=[], now=NOW, extraliga=feed)
    assert out["items"][-1] == {"kind": "more", "count": 0, "href": "client-matches?city=2"}


def test_now_slot_feed_is_chronological_with_dinamo():
    hockey = {"mode": "before", "match": {"id": 1, "starts_at": (NOW + timedelta(days=1)).isoformat()}}
    week = {"kind": "extraliga", "id": 8, "starts_at": (NOW + timedelta(days=6)).isoformat()}
    today = {"kind": "extraliga", "id": 7, "starts_at": (NOW + timedelta(hours=3)).isoformat()}
    feed = {"matches": [today, week], "week_count": 5}
    out = now_slot(bookings=None, hockey=hockey, upcoming=[], now=NOW, extraliga=feed)
    assert [i.get("id") or i["kind"] for i in out["items"]] == [7, "kk_before", 8, "more"]


def test_now_slot_without_feed_or_city_keeps_dinamo():
    hockey = {"mode": "before", "match": {"id": 1}}
    feed = {"matches": [{"kind": "extraliga", "id": 7}], "week_count": 3}
    alone = now_slot(bookings=None, hockey=hockey, upcoming=[], now=NOW)
    assert [i["kind"] for i in alone["items"]] == ["kk_before", "more"]
    assert now_slot(bookings=None, hockey=hockey, upcoming=[], now=NOW, has_city=False, extraliga=feed) is None


# ---------- владелец 2026-11-11: лента до трёх матчей, окно 14 дней, дальний матч, лёд последним ----------

ICE = [{"time": "18:15", "place": "ТЦ Замок"}]


def _at(**delta) -> str:
    return (NOW + timedelta(**delta)).isoformat()


def _kk(mid: int, **delta) -> dict:
    return {"mode": "before", "match": {"id": mid, "starts_at": _at(**delta)}}


def _ids(slot) -> list:
    return [i.get("id") or (i.get("hockey") or {}).get("match", {}).get("id") or i["kind"] for i in slot["items"]]


def test_minsk_without_extraliga_away_dinamo_in_four_days_fills_the_feed():
    hockey = {**_kk(1, days=4), "is_home": False, "next": [], "beyond_window": False}
    slot = now_slot(bookings=None, hockey=hockey, upcoming=ICE, now=NOW, extraliga=None)
    assert slot["kind"] == "feed" and _ids(slot) == [1, "more"]
    assert slot["items"][-1] == {"kind": "more", "count": 0, "href": "client-matches"}


def test_feed_takes_three_nearest_and_all_matches_is_last():
    hockey = {**_kk(1, days=4), "next": [_kk(2, days=6), _kk(3, days=9)], "beyond_window": False}
    xl = {
        "matches": [
            {"kind": "extraliga", "id": 70, "starts_at": _at(days=1)},
            {"kind": "extraliga", "id": 71, "starts_at": _at(days=12)},
        ],
        "week_count": 1,
        "all_href": "client-matches?city=x",
    }
    slot = now_slot(bookings=None, hockey=hockey, upcoming=ICE, now=NOW, extraliga=xl)
    assert _ids(slot) == [70, 1, 2, "more"]
    assert slot["items"][-1] == {"kind": "more", "count": 1, "href": "client-matches?city=x"}


def test_nothing_in_two_weeks_takes_one_far_match_the_earliest_of_dinamo_and_city():
    hockey = {**_kk(1, days=20), "next": [], "beyond_window": True}
    far_xl = {"kind": "extraliga", "id": 70, "starts_at": _at(days=17)}
    slot = now_slot(bookings=None, hockey=hockey, upcoming=ICE, now=NOW, extraliga={"matches": [], "far": far_xl})
    assert _ids(slot) == [70, "more"]
    assert _ids(now_slot(bookings=None, hockey=hockey, upcoming=ICE, now=NOW)) == [1, "more"]
    no_kk = now_slot(bookings=None, hockey={"mode": None}, upcoming=ICE, now=NOW, extraliga={"matches": [], "far": far_xl})
    assert _ids(no_kk) == [70, "more"]


def test_far_dinamo_gives_way_to_city_matches_inside_the_window():
    hockey = {**_kk(1, days=20), "next": [], "beyond_window": True}
    xl = {"matches": [{"kind": "extraliga", "id": 70, "starts_at": _at(days=3)}], "week_count": 1}
    assert _ids(now_slot(bookings=None, hockey=hockey, upcoming=ICE, now=NOW, extraliga=xl)) == [70, "more"]


def test_ice_only_when_no_future_matches_at_all():
    assert now_slot(bookings=None, hockey={"mode": None}, upcoming=ICE, now=NOW, extraliga=None) == {
        "kind": "ice",
        "session": ICE[0],
    }


def test_result_and_waiting_keep_priority_over_the_feed():
    result = {"mode": "result", "match": {"id": 5, "starts_at": _at(hours=-5)}}
    assert now_slot(bookings=None, hockey=result, upcoming=ICE, now=NOW)["kind"] == "kk_result"
    xl = {"matches": [{"kind": "extraliga", "id": 70 + i, "starts_at": _at(days=1 + i)} for i in range(4)]}
    slot = now_slot(bookings=None, hockey=result, upcoming=ICE, now=NOW, extraliga=xl)
    assert _ids(slot) == [5, 70, 71, 72, "more"] and slot["items"][0]["kind"] == "kk_result"
    waiting = {"mode": "waiting", "match": {"id": 6, "starts_at": _at(hours=-1)}, "my_pick": {"side": "home"}}
    slot = now_slot(bookings=None, hockey=waiting, upcoming=ICE, now=NOW)
    assert slot["kind"] == "kk_before" and slot["hockey"]["mode"] == "waiting"
    month = {"mode": "race_result", "race": {"id": 1}}
    slot = now_slot(bookings=None, hockey=month, upcoming=ICE, now=NOW, extraliga=xl)
    assert slot["items"][-2]["kind"] == "kk_month", "итог месяца без даты — перед «Все матчи»"


async def _match(db, sid, home, away, starts, city, arena="Чижовка-Арена"):
    await db.execute(text("""
        INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status, league, city, arena)
        VALUES ('hockeyby', :sid, :home, :away, :starts, 'scheduled', 'extraliga', :city, :arena)
        """), {"sid": sid, "home": home, "away": away, "starts": starts, "city": city, "arena": arena})


@pytest.mark.asyncio
async def test_home_feed_only_matches_that_happen_in_the_city(db_session, monkeypatch):
    """Правило A: выезд местного клуба и матч области в слот города не попадают; счётчик — по этому городу."""
    monkeypatch.setenv("EXTRALIGA_ENABLED", "1")
    monkeypatch.setenv("EXTRALIGA_CLUBS", "Юность,Неман,Брест")
    await db_session.execute(text("DELETE FROM hockey_matches WHERE league = 'extraliga'"))
    await _match(db_session, "t1", "Юность", "Неман", NOW + timedelta(hours=7), "Минск")
    await _match(db_session, "t2", "Брест", "Юность", NOW + timedelta(days=2), "Брест", "Брест-Арена")
    await _match(db_session, "t3", "Неман", "Брест", NOW + timedelta(days=3), "Гродно", "Гродно-Арена")
    await db_session.commit()
    feed = await extraliga_home.home_feed(db_session, city_name="Минск", city_region=None, now=NOW, settings=Settings())
    assert [(m["home"]["name"], m["sticker"]) for m in feed["matches"]] == [("Юность", "СЕГОДНЯ")]
    assert feed["week_count"] == 1 and feed["all_href"].startswith("client-matches?city=")
    grodno = await extraliga_home.home_feed(db_session, city_name="Гродно", city_region=None, now=NOW, settings=Settings())
    assert [m["home"]["name"] for m in grodno["matches"]] == ["Неман"] and grodno["week_count"] == 1
    # В Пинске ничего не идёт: ни «области», ни чужих выездов.
    assert await extraliga_home.home_feed(db_session, city_name="Пинск", city_region="Брестская", now=NOW, settings=Settings()) is None


@pytest.mark.asyncio
async def test_home_feed_window_is_two_weeks_and_far_match_when_empty(db_session, monkeypatch):
    """Окно ленты 14 дней (счёт «на неделе» — за 7); пусто в окне — один ближайший будущий матч города."""
    monkeypatch.setenv("EXTRALIGA_ENABLED", "1")
    monkeypatch.setenv("EXTRALIGA_CLUBS", "Юность,Неман,Брест")
    await db_session.execute(text("DELETE FROM hockey_matches WHERE league = 'extraliga'"))
    await _match(db_session, "w1", "Неман", "Брест", NOW + timedelta(days=2), "Гродно")
    await _match(db_session, "w2", "Неман", "Юность", NOW + timedelta(days=10), "Гродно")
    await _match(db_session, "f1", "Брест", "Неман", NOW + timedelta(days=25), "Брест")
    await _match(db_session, "f2", "Брест", "Юность", NOW + timedelta(days=20), "Брест")
    await db_session.commit()
    grodno = await extraliga_home.home_feed(db_session, city_name="Гродно", city_region=None, now=NOW, settings=Settings())
    assert [m["away"]["name"] for m in grodno["matches"]] == ["Брест", "Юность"] and grodno["week_count"] == 1
    brest = await extraliga_home.home_feed(db_session, city_name="Брест", city_region=None, now=NOW, settings=Settings())
    assert brest["matches"] == [] and brest["far"]["away"]["name"] == "Юность"
