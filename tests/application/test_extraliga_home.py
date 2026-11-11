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
    return (await db.execute(text("""
        INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status, league, city, arena)
        VALUES ('hockeyby', :sid, :home, :away, :starts, 'scheduled', 'extraliga', :city, :arena) RETURNING id
        """), {"sid": sid, "home": home, "away": away, "starts": starts, "city": city, "arena": arena})).scalar_one()


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


# --- Лента «сейчас»: только домашние матчи (Экстралига города + Динамо дома), до трёх, 14 дней, дальний, лёд ---

ICE_UPCOMING = [{"time": "18:15", "place": "ТЦ Замок"}]


async def _dinamo(db, sid, home, away, starts):
    return (await db.execute(text("""
        INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status)
        VALUES ('hcdinamo', :sid, :home, :away, :starts, 'scheduled') RETURNING id
        """), {"sid": sid, "home": home, "away": away, "starts": starts})).scalar_one()


async def _clean(db, monkeypatch, clubs="Юность,Неман,Брест"):
    monkeypatch.setenv("EXTRALIGA_ENABLED", "1")
    monkeypatch.setenv("EXTRALIGA_CLUBS", clubs)
    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "1")
    await db.execute(text("DELETE FROM hockey_matches"))


async def _slot(db, *, hockey=None, upcoming=(), city="Минск"):
    feed = await extraliga_home.home_feed(db, city_name=city, city_region=None, now=NOW, settings=Settings())
    return feed, now_slot(bookings=None, hockey=hockey, upcoming=list(upcoming), now=NOW, extraliga=feed)


@pytest.mark.asyncio
async def test_minsk_dinamo_away_is_skipped_nearest_home_shown_even_beyond_window(db_session, monkeypatch):
    """(а) Минск, своих матчей нет: выезды Динамо через 2 и 4 дня не показываем — ближайший домашний, хоть через 20 дней."""
    await _clean(db_session, monkeypatch)
    await _dinamo(db_session, "d1", "СКА", "Динамо-Минск", NOW + timedelta(days=2))
    await _dinamo(db_session, "d2", "Барыс", "Динамо-Минск", NOW + timedelta(days=4))
    home = await _dinamo(db_session, "d3", "Динамо-Минск", "Сочи", NOW + timedelta(days=20))
    await db_session.commit()
    _feed, out = await _slot(db_session, hockey={"mode": None}, upcoming=ICE_UPCOMING)
    items = out["items"]
    assert [i.get("id") or i["kind"] for i in items] == [home, "more"]
    card = items[0]
    assert card["kind"] == "extraliga" and card["href"] == f"client-match?id={home}"
    assert "hockey" not in card and "my_pick" not in card
    assert (card["arena"], card["city"]) == ("Минск-Арена", "Минск")
    assert items[-1]["count"] == 0  # на неделе матчей Экстралиги в Минске нет


@pytest.mark.asyncio
async def test_dinamo_home_matches_shown_in_every_city(db_session, monkeypatch):
    """(а') Динамо — общебелорусский бренд: его домашние матчи видны и в Гродно, рядом с домашними «Немана»."""
    await _clean(db_session, monkeypatch)
    neman = await _match(db_session, "x1", "Неман", "Юность", NOW + timedelta(days=5), "Гродно", "Гродно-Арена")
    await _match(db_session, "x2", "Брест", "Неман", NOW + timedelta(days=2), "Брест", "Брест-Арена")  # выезд Немана
    home = await _dinamo(db_session, "d1", "Динамо-Минск", "Барыс", NOW + timedelta(days=9))
    await _dinamo(db_session, "d2", "СКА", "Динамо-Минск", NOW + timedelta(days=3))
    await db_session.commit()
    _feed, out = await _slot(db_session, city="Гродно")
    assert [i.get("id") or i["kind"] for i in out["items"]] == [neman, home, "more"]


@pytest.mark.asyncio
async def test_feed_keeps_three_nearest_home_matches_then_more(db_session, monkeypatch):
    """(б) Домашних больше трёх — три ближайших по времени, «Все матчи» последней; выезды не занимают места."""
    await _clean(db_session, monkeypatch)
    x1 = await _match(db_session, "x1", "Юность", "Неман", NOW + timedelta(days=1), "Минск")
    x2 = await _match(db_session, "x2", "Юность", "Брест", NOW + timedelta(days=10), "Минск")
    await _match(db_session, "x3", "Брест", "Юность", NOW + timedelta(days=3), "Брест", "Брест-Арена")  # выезд Юности
    d1 = await _dinamo(db_session, "d1", "Динамо-Минск", "Барыс", NOW + timedelta(days=2))
    await _dinamo(db_session, "d2", "СКА", "Динамо-Минск", NOW + timedelta(days=5))  # выезд Динамо
    await _dinamo(db_session, "d3", "Динамо-Минск", "Сочи", NOW + timedelta(days=12))
    await db_session.commit()
    _feed, out = await _slot(db_session)
    items = out["items"]
    assert [i.get("id") or i["kind"] for i in items] == [x1, d1, x2, "more"]
    assert items[-1]["count"] == 1


@pytest.mark.asyncio
async def test_empty_window_shows_one_far_home_match(db_session, monkeypatch):
    """(в) В 14 днях домашних нет (только выезд) — один ближайший будущий домашний матч, пусть и через месяц."""
    await _clean(db_session, monkeypatch)
    await _dinamo(db_session, "d0", "СКА", "Динамо-Минск", NOW + timedelta(days=6))
    far = await _dinamo(db_session, "d1", "Динамо-Минск", "Барыс", NOW + timedelta(days=30))
    await _dinamo(db_session, "d2", "Динамо-Минск", "Сочи", NOW + timedelta(days=33))
    await _dinamo(db_session, "d3", "Динамо-Минск", "Сочи", NOW - timedelta(days=20))  # прошёл, итога в базе нет
    await db_session.commit()
    _feed, out = await _slot(db_session, upcoming=ICE_UPCOMING)
    assert [i.get("id") or i["kind"] for i in out["items"]] == [far, "more"]


@pytest.mark.asyncio
async def test_no_future_home_matches_falls_back_to_ice(db_session, monkeypatch):
    """(г) Домашних будущих матчей нет совсем (только выезды и прошедшие) — слот «Ближайший лёд»."""
    await _clean(db_session, monkeypatch)
    await _dinamo(db_session, "d0", "Динамо-Минск", "Сочи", NOW - timedelta(days=20))
    await _dinamo(db_session, "d1", "СКА", "Динамо-Минск", NOW + timedelta(days=40))
    await _match(db_session, "x1", "Брест", "Юность", NOW + timedelta(days=3), "Брест", "Брест-Арена")
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
    later = await _dinamo(db_session, "d2", "Динамо-Минск", "Сочи", NOW + timedelta(days=8))
    await db_session.commit()
    hockey = await hub_card(db_session, 990001, now=NOW)
    assert hockey["mode"] == "before" and hockey["match"]["id"] == home
    _feed, out = await _slot(db_session, hockey=hockey)
    items = out["items"]
    assert [i["kind"] for i in items] == ["kk_before", "extraliga", "more"]
    assert items[0] == {"kind": "kk_before", "hockey": hockey}
    assert items[1]["id"] == later
    assert all(i.get("id") != home for i in items[1:])


@pytest.mark.asyncio
async def test_every_plain_card_opens_on_the_match_page(db_session, monkeypatch):
    """Ни одной карточки, которую страница матча не откроет: нет выездов Динамо и выездов клубов города."""
    from src.application.hockey_event import _home_match
    from src.application.site_matches import place_of

    await _clean(db_session, monkeypatch)
    await _match(db_session, "x1", "Юность", "Неман", NOW + timedelta(days=1), "Минск")
    await _match(db_session, "x2", "Неман", "Юность", NOW + timedelta(days=2), "Гродно", "Гродно-Арена")
    await _match(db_session, "x3", "Брест", "Неман", NOW + timedelta(days=4), "Брест", "Брест-Арена")
    await _dinamo(db_session, "d1", "СКА", "Динамо-Минск", NOW + timedelta(hours=30))
    await _dinamo(db_session, "d2", "Динамо-Минск", "Барыс", NOW + timedelta(days=6))
    await _dinamo(db_session, "d3", "Сочи", "Динамо-Минск", NOW + timedelta(days=8))
    await db_session.commit()
    for city in ("Минск", "Гродно", "Брест", "Пинск"):
        _feed, out = await _slot(db_session, city=city)
        plain = [i for i in out["items"] if i["kind"] == "extraliga"]
        assert plain, city
        for item in plain:
            assert item["href"] == f"client-match?id={item['id']}"
            row = await _home_match(db_session, item["id"])  # MatchNotFound — страница матча не откроется
            assert row.home_team == "Динамо-Минск" or place_of(row)[1] == city, (city, row.home_team, row.away_team)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("home", "away", "arena", "city"),
    [
        ("Юность", "Локомотив Орша", "Чижовка-Арена", "Минск"),
        ("Витебск", "Могилев", "Витебский дворец спорта", "Витебск"),
        ("Металлург Жлобин", "Гомель", "Ледовый дворец «Металлург»", "Жлобин"),
    ],
)
async def test_home_match_with_null_city_counts_for_the_club_city(db_session, monkeypatch, home, away, arena, city):
    """Как на проде: у домашних матчей hockey.by city = NULL. Город — как у страницы матча (place_of: клуб-хозяин)."""
    await _clean(db_session, monkeypatch, clubs=f"{home},{away}")
    far = await _match(db_session, "n1", home, away, NOW + timedelta(days=20), None, arena)
    await db_session.commit()
    # Других матчей нет — домашний вне окна встаёт «одним ближайшим».
    feed = await extraliga_home.home_feed(db_session, city_name=city, city_region=None, now=NOW, settings=Settings())
    assert [m["id"] for m in feed["matches"]] == [far] and feed["week_count"] == 0
    assert feed["matches"][0]["arena"] == arena
    # В окне и на этой неделе — в ленте и в счётчике «N матчей на неделе».
    near = await _match(db_session, "n2", home, away, NOW + timedelta(days=2), None, arena)
    await db_session.commit()
    feed = await extraliga_home.home_feed(db_session, city_name=city, city_region=None, now=NOW, settings=Settings())
    assert [m["id"] for m in feed["matches"]] == [near] and feed["week_count"] == 1
    # Гостю этот матч в его городе не показываем.
    guest_city = {"Локомотив Орша": "Орша", "Могилев": "Могилев", "Гомель": "Гомель"}[away]
    assert await extraliga_home.home_feed(
        db_session, city_name=guest_city, city_region=None, now=NOW, settings=Settings()
    ) is None


@pytest.mark.asyncio
async def test_dinamo_card_has_exactly_the_extraliga_card_keys(db_session, monkeypatch):
    """(ж) Карточка Динамо из ленты и карточка Экстралиги — один и тот же набор ключей (рисует xlCard)."""
    await _clean(db_session, monkeypatch)
    await _match(db_session, "x1", "Юность", "Неман", NOW + timedelta(days=1), "Минск")
    await _dinamo(db_session, "d1", "Динамо-Минск", "Барыс", NOW + timedelta(days=2))
    await db_session.commit()
    feed, _out = await _slot(db_session)
    xl, dinamo = feed["matches"]
    assert xl["home"]["name"] == "Юность" and dinamo["home"]["name"] == "Динамо-Минск"
    assert set(dinamo) == set(xl)
    assert set(dinamo["home"]) == set(xl["home"]) and set(dinamo["away"]) == set(xl["away"])
    assert dinamo["kind"] == "extraliga" and dinamo["result"] is None and dinamo["live"] is False
