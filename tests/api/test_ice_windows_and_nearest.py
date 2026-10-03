"""TASK-146: окно времени в ленте (Q-006) и «Лёд рядом сейчас» (Q-013)."""

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


async def _session(db_session, arena_id: int, *, day: date, hhmm: str) -> int:
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


@pytest.mark.asyncio
async def test_window_puts_in_window_rinks_first_and_says_when_nothing_fits(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Окнинск {uuid.uuid4().hex[:6]}")
    soon = await _insert_arena(db_session, city_id, name=f"Ранний {uuid.uuid4().hex[:4]}")
    later = await _insert_arena(db_session, city_id, name=f"Поздний {uuid.uuid4().hex[:4]}")
    base = date.today() + timedelta(days=3)
    await _session(db_session, soon, day=base, hhmm="10:00")
    await _session(db_session, later, day=base + timedelta(days=5), hhmm="12:00")
    await db_session.commit()

    async with _client() as client:
        tomorrow = await client.get("/api/public/ice/arenas", params={"city_id": city_id, "when": "tomorrow"})
        anytime = await client.get("/api/public/ice/arenas", params={"city_id": city_id})
    body = tomorrow.json()
    assert body["window"]["key"] == "tomorrow" and body["window"]["label"] == "Завтра"
    assert body["window"]["hits"] == 0
    # Лента не пустая: оба катка на месте, с пометкой «вне окна».
    assert {i["id"] for i in body["items"]} >= {soon, later}
    assert all(i["live"].get("outside_window") for i in body["items"] if i["id"] in (soon, later))
    assert anytime.json()["window"] is None


@pytest.mark.asyncio
async def test_auto_window_is_resolved_on_the_server(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Автинск {uuid.uuid4().hex[:6]}")
    await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    async with _client() as client:
        body = (await client.get("/api/public/ice/arenas", params={"city_id": city_id, "when": "auto"})).json()
        coach = (
            await client.get("/api/public/ice/arenas", params={"city_id": city_id, "when": "auto", "intent": "coach"})
        ).json()
    assert body["window"]["key"] in ("today_evening", "tomorrow", "weekend")
    assert coach["window"] is None, "у тренеров — слоты недели, окно к ним не применяется"


@pytest.mark.asyncio
async def test_nearest_ice_prefers_today_then_the_soonest_day(app_use_test_db, db_session) -> None:
    from datetime import datetime, time, timezone
    from zoneinfo import ZoneInfo

    from src.application.arena_public_use_cases import find_nearest_ice_now

    city_id = await _insert_city(db_session, name=f"Ближинск {uuid.uuid4().hex[:6]}")
    near_rink = await _insert_arena(
        db_session, city_id, name=f"Рядом {uuid.uuid4().hex[:4]}", latitude=10.001, longitude=10.001
    )
    far_rink = await _insert_arena(
        db_session, city_id, name=f"Далеко {uuid.uuid4().hex[:4]}", latitude=10.2, longitude=10.2
    )
    day = date.today() + timedelta(days=40)
    await _session(db_session, far_rink, day=day, hhmm="09:00")
    await _session(db_session, near_rink, day=day, hhmm="20:00")
    await _session(db_session, near_rink, day=day + timedelta(days=1), hhmm="09:00")
    await db_session.commit()

    morning = datetime.combine(day, time(7, 0), tzinfo=ZoneInfo("Europe/Minsk")).astimezone(timezone.utc)
    today_pick = await find_nearest_ice_now(db_session, near="10.0,10.0", now=morning)
    assert today_pick["is_today"] is True
    assert today_pick["arena_id"] == near_rink, "сегодня — ближайший каток, а не самый ранний сеанс"
    assert today_pick["starts_at_local"] == "20:00"

    evening = datetime.combine(day, time(21, 0), tzinfo=ZoneInfo("Europe/Minsk")).astimezone(timezone.utc)
    next_day = await find_nearest_ice_now(db_session, near="10.0,10.0", now=evening)
    assert next_day["is_today"] is False and next_day["day_label"] == "Завтра"

    async with _client() as client:
        bad = await client.get("/api/public/ice/nearest", params={"near": "x"})
    assert bad.status_code == 400
