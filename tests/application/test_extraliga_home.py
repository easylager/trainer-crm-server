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
async def test_home_feed_city_and_away_games_with_one_sticker(db_session, monkeypatch):
    monkeypatch.setenv("EXTRALIGA_ENABLED", "1")
    monkeypatch.setenv("EXTRALIGA_CLUBS", "Юность,Неман,Брест")
    await db_session.execute(text("DELETE FROM hockey_matches WHERE league = 'extraliga'"))
    await _match(db_session, "t1", "Юность", "Неман", NOW + timedelta(hours=7), "Минск")
    await _match(db_session, "t2", "Брест", "Юность", NOW + timedelta(days=2), "Брест", "Брест-Арена")
    await _match(db_session, "t3", "Неман", "Брест", NOW + timedelta(days=3), "Гродно", "Гродно-Арена")
    await db_session.commit()
    feed = await extraliga_home.home_feed(db_session, city_name="Минск", city_region=None, now=NOW, settings=Settings())
    assert [(m["home"]["name"], m["sticker"]) for m in feed["matches"]] == [("Юность", "СЕГОДНЯ"), ("Брест", None)]
    assert feed["week_count"] == 3
    grodno = await extraliga_home.home_feed(db_session, city_name="Гродно", city_region=None, now=NOW, settings=Settings())
    # Выезд Немана в Минск и домашний матч через 3 дня: наклейка только сегодня/завтра.
    assert [(m["home"]["name"], m["sticker"]) for m in grodno["matches"]] == [("Юность", None), ("Неман", None)]
