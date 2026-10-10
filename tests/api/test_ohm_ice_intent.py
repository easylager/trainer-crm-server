"""TASK-201-B: Mini App / API intent=ohm — только катки с будущим hockey_practice."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _mk(db_session, arena_id: int, *, day: date, hhmm: str) -> int:
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=day,
        starts_at_local=hhmm,
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=1000,
    )
    await db_session.flush()
    return int(created["id"])


async def _ohm(db_session, arena_id: int, *, day: date, hhmm: str) -> int:
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=day,
        starts_at_local=hhmm,
        duration_minutes=60,
        kind="hockey_practice",
        price_adult_minor=1700,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.flush()
    return int(created["id"])


@pytest.mark.asyncio
async def test_intent_ohm_lists_only_arenas_with_hockey_practice(app_use_test_db, db_session) -> None:
    name = f"OhmIntent {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    ohm_rink = await _insert_arena(db_session, city_id, name=f"OHM rink {uuid.uuid4().hex[:4]}")
    mk_only = await _insert_arena(db_session, city_id, name=f"MK only {uuid.uuid4().hex[:4]}")
    day = date.today() + timedelta(days=2)
    ohm_id = await _ohm(db_session, ohm_rink, day=day, hhmm="08:45")
    await _mk(db_session, mk_only, day=day, hhmm="15:00")
    await _mk(db_session, ohm_rink, day=day, hhmm="19:00")
    await db_session.commit()

    async with _client() as client:
        ohm = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": city_id, "intent": "ohm", "limit": 50},
        )
        skate = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": city_id, "intent": "skate", "limit": 50},
        )
        cities = await client.get("/api/public/ice/cities")

    assert ohm.status_code == 200
    ohm_items = ohm.json()["items"]
    assert len(ohm_items) == 1
    assert ohm_items[0]["id"] == ohm_rink
    live = ohm_items[0].get("live") or {}
    assert live.get("session_id") == ohm_id
    assert "08:45" in str(live.get("text") or "")

    skate_ids = {int(i["id"]) for i in skate.json()["items"]}
    assert ohm_rink in skate_ids
    assert mk_only in skate_ids
    for item in skate.json()["items"]:
        if int(item["id"]) == ohm_rink:
            # МК live не должен указывать на ОХМ-сеанс
            assert (item.get("live") or {}).get("session_id") != ohm_id

    assert cities.status_code == 200
    city_row = next(c for c in cities.json()["items"] if int(c["id"]) == city_id)
    assert int(city_row.get("ohm_count") or 0) == 1


@pytest.mark.asyncio
async def test_ohm_when_puts_that_day_first(app_use_test_db, db_session) -> None:
    """Чип «Завтра» на ОХМ — сеанс завтра сверху, более поздний не притворяется ответом."""
    name = f"OhmWhen {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    later = await _insert_arena(db_session, city_id, name=f"Later {uuid.uuid4().hex[:4]}")
    tomorrow_rink = await _insert_arena(db_session, city_id, name=f"Tomorrow {uuid.uuid4().hex[:4]}")
    tomorrow = date.today() + timedelta(days=1)
    later_day = date.today() + timedelta(days=3)
    await _ohm(db_session, later, day=later_day, hhmm="13:00")
    await _ohm(db_session, tomorrow_rink, day=tomorrow, hhmm="10:00")
    await db_session.commit()

    async with _client() as client:
        res = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": city_id, "intent": "ohm", "when": "tomorrow", "limit": 50},
        )

    assert res.status_code == 200
    body = res.json()
    assert (body.get("window") or {}).get("key") == "tomorrow"
    items = body["items"]
    assert [int(i["id"]) for i in items][:1] == [tomorrow_rink]
    assert "10:00" in str((items[0].get("live") or {}).get("text") or "")
    assert (items[0].get("live") or {}).get("outside_window") is False
    later_item = next(i for i in items if int(i["id"]) == later)
    assert (later_item.get("live") or {}).get("outside_window") is True


@pytest.mark.asyncio
async def test_arena_sessions_include_ohm_days(app_use_test_db, db_session) -> None:
    name = f"OhmSess {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink = await _insert_arena(db_session, city_id, name=f"Sess rink {uuid.uuid4().hex[:4]}")
    day = date.today() + timedelta(days=1)
    ohm_id = await _ohm(db_session, rink, day=day, hhmm="09:30")
    mk_id = await _mk(db_session, rink, day=day, hhmm="18:00")
    await db_session.commit()

    async with _client() as client:
        res = await client.get(f"/api/public/arenas/{rink}/sessions")

    assert res.status_code == 200
    body = res.json()
    mk_ids = {
        int(s["id"])
        for d in body.get("days") or []
        for s in d.get("sessions") or []
    }
    ohm_ids = {
        int(s["id"])
        for d in body.get("ohm_days") or []
        for s in d.get("sessions") or []
    }
    assert mk_id in mk_ids
    assert ohm_id not in mk_ids
    assert ohm_id in ohm_ids
    assert mk_id not in ohm_ids
