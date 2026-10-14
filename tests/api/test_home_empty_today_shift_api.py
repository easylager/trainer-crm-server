"""Главная и /c/{город}?w=today: вечером без будущих сеансов — вкладка «Завтра» и подпись."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Europe/Minsk")).astimezone(timezone.utc)


@pytest.mark.asyncio
async def test_catalog_home_shifts_to_tomorrow_evening(app_use_test_db, db_session, monkeypatch) -> None:
    fixed = _utc(2026, 10, 7, 22, 30)
    monkeypatch.setattr("src.application.catalog_home_page._utc_now", lambda: fixed)

    name = f"Вечер {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    today = fixed.astimezone(ZoneInfo("Europe/Minsk")).date()
    await create_ice_session(
        db_session,
        arena_id,
        local_date=today,
        starts_at_local="10:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    tomorrow = today + timedelta(days=1)
    await create_ice_session(
        db_session,
        arena_id,
        local_date=tomorrow,
        starts_at_local="11:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/")
        explicit = await client.get("/?when=today")

    assert home.status_code == 200
    assert 'href="/?when=tomorrow" aria-current="true"' in home.text
    assert "На сегодня всё — вот завтра" in home.text
    assert "1 сеанс" in home.text.replace("\u00a0", " ")

    assert explicit.status_code == 200
    assert explicit.url.path == "/" and "when=today" in str(explicit.url)
    assert 'href="/?when=today" aria-current="true"' in explicit.text
    assert "На сегодня всё — вот завтра" not in explicit.text


def _freeze_modules(monkeypatch, fixed: datetime, *modules: str) -> None:
    import datetime as dt

    class _Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return fixed.astimezone(tz)
            return fixed.replace(tzinfo=None)

    for mod in modules:
        monkeypatch.setattr(f"{mod}.datetime", _Clock)


@pytest.mark.asyncio
async def test_city_ice_list_shifts_to_tomorrow_without_url_change(app_use_test_db, db_session, monkeypatch) -> None:
    fixed = _utc(2026, 10, 7, 23, 59)
    _freeze_modules(
        monkeypatch,
        fixed,
        "src.application.selection_page",
        "src.application.arena_public_use_cases",
    )

    name = f"Список {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    today = fixed.astimezone(ZoneInfo("Europe/Minsk")).date()
    await create_ice_session(
        db_session,
        arena_id,
        local_date=today,
        starts_at_local="08:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    tomorrow = today + timedelta(days=1)
    await create_ice_session(
        db_session,
        arena_id,
        local_date=tomorrow,
        starts_at_local="12:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        resp = await client.get(f"/c/{slug}", params={"t": "ice", "w": "today"})

    assert resp.status_code == 200
    assert "w=today" in str(resp.url)
    assert "На сегодня всё — вот завтра" in resp.text
    assert "12:00" in resp.text
    assert "сеансов нет — показываем ближайшие" not in resp.text


@pytest.mark.asyncio
async def test_only_past_sessions_today_no_shift_when_tomorrow_empty(app_use_test_db, db_session, monkeypatch) -> None:
    fixed = _utc(2026, 10, 7, 21, 0)
    monkeypatch.setattr("src.application.catalog_home_page._utc_now", lambda: fixed)

    name = f"Пусто {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    later = fixed.astimezone(ZoneInfo("Europe/Minsk")).date() + timedelta(days=4)
    await create_ice_session(
        db_session,
        arena_id,
        local_date=later,
        starts_at_local="10:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/")

    assert home.status_code == 200
    assert "На сегодня всё" in home.text
    assert 'href="/?when=tomorrow" aria-current="true"' in home.text or re.search(
        r"вот (ср|чт|пт|сб|вс|завтра)", home.text.lower()
    )

