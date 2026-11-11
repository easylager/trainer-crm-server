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
    assert now_slot(bookings=None, hockey=hockey, upcoming=[], now=NOW)["kind"] == "kk_before"
    assert now_slot(bookings=None, hockey=hockey, upcoming=[], now=NOW, has_city=False, extraliga=feed) is None


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


# --- Лента «сейчас»: до трёх ближайших матчей (город + Динамо), окно 14 дней, дальний матч, лёд в межсезонье ---

ICE_UPCOMING = [{"time": "18:15", "place": "ТЦ Замок"}]


async def _dinamo(db, sid, home, away, starts, status="scheduled"):
    return (await db.execute(text("""
        INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status)
        VALUES ('hcdinamo', :sid, :home, :away, :starts, :status) RETURNING id
        """), {"sid": sid, "home": home, "away": away, "starts": starts, "status": status})).scalar_one()


async def _clean(db, monkeypatch, clubs="Юность,Неман,Брест"):
    monkeypatch.setenv("EXTRALIGA_ENABLED", "1")
    monkeypatch.setenv("EXTRALIGA_CLUBS", clubs)
    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "1")
    await db.execute(text("DELETE FROM hockey_matches"))


async def _slot(db, *, hockey=None, upcoming=(), city="Минск"):
    feed = await extraliga_home.home_feed(db, city_name=city, city_region=None, now=NOW, settings=Settings())
    return feed, now_slot(bookings=None, hockey=hockey, upcoming=list(upcoming), now=NOW, extraliga=feed)


@pytest.mark.asyncio
async def test_minsk_dinamo_away_and_home_become_plain_match_cards(db_session, monkeypatch):
    """(а) Минск, своих матчей Экстралиги нет: выезд Динамо через 4 дня и дом через 9 — две обычные карточки + «все»."""
    await _clean(db_session, monkeypatch)
    away = await _dinamo(db_session, "d1", "СКА", "Динамо-Минск", NOW + timedelta(days=4))
    home = await _dinamo(db_session, "d2", "Динамо-Минск", "Барыс", NOW + timedelta(days=9))
    await db_session.commit()
    _feed, out = await _slot(db_session, hockey={"mode": None}, upcoming=ICE_UPCOMING)
    assert out["kind"] == "feed"
    items = out["items"]
    assert [i["kind"] for i in items] == ["extraliga", "extraliga", "more"]
    assert [i["id"] for i in items[:2]] == [away, home]
    assert [i["href"] for i in items[:2]] == [f"client-match?id={away}", f"client-match?id={home}"]
    assert all("hockey" not in i and "my_pick" not in i for i in items)
    assert (items[0]["arena"], items[0]["city"]) == (None, None)
    assert (items[1]["arena"], items[1]["city"]) == ("Минск-Арена", "Минск")
    assert items[-1]["count"] == 0  # на неделе матчей Экстралиги в Минске нет


@pytest.mark.asyncio
async def test_feed_keeps_three_nearest_then_more(db_session, monkeypatch):
    """(б) Матчей больше трёх — три ближайших по времени, «Все матчи» последней; счёт за 7 дней — по городу."""
    await _clean(db_session, monkeypatch)
    await _match(db_session, "x1", "Юность", "Неман", NOW + timedelta(days=1), "Минск")
    await _match(db_session, "x2", "Юность", "Брест", NOW + timedelta(days=10), "Минск")
    d1 = await _dinamo(db_session, "d1", "Динамо-Минск", "Барыс", NOW + timedelta(days=2))
    await _dinamo(db_session, "d2", "СКА", "Динамо-Минск", NOW + timedelta(days=5))
    await _dinamo(db_session, "d3", "Динамо-Минск", "Сочи", NOW + timedelta(days=12))
    await db_session.commit()
    _feed, out = await _slot(db_session)
    items = out["items"]
    assert [i["kind"] for i in items] == ["extraliga", "extraliga", "extraliga", "more"]
    starts = [i["starts_at"] for i in items[:3]]
    assert starts == sorted(starts) and items[1]["id"] == d1
    assert items[-1]["kind"] == "more" and items[-1]["count"] == 1


@pytest.mark.asyncio
async def test_empty_window_shows_one_far_match(db_session, monkeypatch):
    """(в) В 14 днях ничего нет — один ближайший будущий матч, пусть и через месяц; лёд не встаёт."""
    await _clean(db_session, monkeypatch)
    far = await _dinamo(db_session, "d1", "Динамо-Минск", "Барыс", NOW + timedelta(days=30))
    await _dinamo(db_session, "d2", "СКА", "Динамо-Минск", NOW + timedelta(days=33))
    await _dinamo(db_session, "d0", "Динамо-Минск", "Сочи", NOW - timedelta(days=20))  # прошёл, итога в базе нет
    await db_session.commit()
    _feed, out = await _slot(db_session, upcoming=ICE_UPCOMING)
    assert [i.get("id") or i["kind"] for i in out["items"]] == [far, "more"]


@pytest.mark.asyncio
async def test_no_future_matches_falls_back_to_ice(db_session, monkeypatch):
    """(г) Межсезонье: будущих матчей нет совсем — слот «Ближайший лёд»."""
    await _clean(db_session, monkeypatch)
    await _dinamo(db_session, "d0", "Динамо-Минск", "Сочи", NOW - timedelta(days=20))  # прошёл, итога в базе нет
    await db_session.commit()
    feed, out = await _slot(db_session, upcoming=ICE_UPCOMING)
    assert feed is None
    assert out == {"kind": "ice", "session": ICE_UPCOMING[0]}


@pytest.mark.asyncio
async def test_game_card_stays_and_its_match_is_not_duplicated(db_session, monkeypatch):
    """(д) Домашнему Динамо положена игровая карточка (kk_before) — она та же, что и раньше, обычной копии нет."""
    from src.application.hockey_hub import hub_card

    await _clean(db_session, monkeypatch)
    home = await _dinamo(db_session, "d1", "Динамо-Минск", "Барыс", NOW + timedelta(days=3))
    away = await _dinamo(db_session, "d2", "СКА", "Динамо-Минск", NOW + timedelta(days=6))
    await db_session.commit()
    hockey = await hub_card(db_session, 990001, now=NOW)
    assert hockey["mode"] == "before" and hockey["match"]["id"] == home
    _feed, out = await _slot(db_session, hockey=hockey)
    items = out["items"]
    assert [i["kind"] for i in items] == ["kk_before", "extraliga", "more"]
    assert items[0] == {"kind": "kk_before", "hockey": hockey}
    assert items[1]["id"] == away
    assert all(i.get("id") != home for i in items[1:])


@pytest.mark.asyncio
async def test_dinamo_card_has_exactly_the_extraliga_card_keys(db_session, monkeypatch):
    """(ж) Карточка Динамо из ленты и карточка Экстралиги — один и тот же набор ключей (рисует xlCard)."""
    await _clean(db_session, monkeypatch)
    await _match(db_session, "x1", "Юность", "Неман", NOW + timedelta(days=1), "Минск")
    await _dinamo(db_session, "d1", "СКА", "Динамо-Минск", NOW + timedelta(days=2))
    await db_session.commit()
    feed, _out = await _slot(db_session)
    xl, dinamo = feed["matches"]
    assert xl["home"]["name"] == "Юность" and dinamo["away"]["name"] == "Динамо-Минск"
    assert set(dinamo) == set(xl)
    assert set(dinamo["home"]) == set(xl["home"]) and set(dinamo["away"]) == set(xl["away"])
    assert dinamo["kind"] == "extraliga" and dinamo["result"] is None and dinamo["live"] is False


@pytest.mark.asyncio
async def test_dinamo_not_added_in_russian_city(db_session, monkeypatch):
    await _clean(db_session, monkeypatch)
    await _dinamo(db_session, "d1", "Динамо-Минск", "Барыс", NOW + timedelta(days=3))
    await db_session.commit()
    feed = await extraliga_home.home_feed(
        db_session, city_name="Санкт-Петербург", city_region=None, city_country="RU", now=NOW, settings=Settings()
    )
    assert feed is None
