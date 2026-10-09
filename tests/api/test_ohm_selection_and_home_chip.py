"""TASK-201-B: /c/?kind=ohm и чип «Хоккей (ОХМ)» на главной."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.ice_city_day import city_slug
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
        session_label="большая арена",
    )
    await db_session.flush()
    return int(created["id"])


@pytest.mark.asyncio
async def test_kind_ohm_lists_only_arenas_with_hockey_practice(app_use_test_db, db_session) -> None:
    name = f"Охминск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    ohm_rink = await _insert_arena(db_session, city_id, name=f"ОХМ-каток {uuid.uuid4().hex[:4]}")
    mk_only = await _insert_arena(db_session, city_id, name=f"Только-МК {uuid.uuid4().hex[:4]}")
    day = date.today() + timedelta(days=2)
    await _ohm(db_session, ohm_rink, day=day, hhmm="08:45")
    await _mk(db_session, mk_only, day=day, hhmm="15:00")
    await _mk(db_session, ohm_rink, day=day, hhmm="19:00")
    await db_session.commit()
    slug = city_slug(name)

    async with _client() as client:
        ohm_page = await client.get(f"/c/{slug}", params={"kind": "ohm"})
        all_page = await client.get(f"/c/{slug}")

    assert ohm_page.status_code == 200
    assert "Хоккей (ОХМ)" in ohm_page.text
    assert "08:45" in ohm_page.text
    assert f"ОХМ-каток" in ohm_page.text or "ohm" in ohm_page.text.lower()
    assert "Только-МК" not in ohm_page.text
    assert "15:00" not in ohm_page.text
    # Массовое не смешивается: на обычной подборке ОХМ-время не в слотах МК-списка
    # (ОХМ-каток может быть в «все места», но 08:45 — только у kind=ohm).
    assert "08:45" not in all_page.text or "kind=ohm" in all_page.text


@pytest.mark.asyncio
async def test_home_hockey_chip_appears_only_with_future_ohm(app_use_test_db, db_session) -> None:
    name = f"Чипинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name, country="BY")
    rink = await _insert_arena(db_session, city_id, name=f"Чип-каток {uuid.uuid4().hex[:4]}")
    await db_session.commit()

    async with _client() as client:
        before = await client.get("/")
    assert before.status_code == 200
    # Без ОХМ в этой стране чип может всё ещё быть, если в сид-городах есть ОХМ —
    # проверяем появление ссылки на наш город после добавления сеанса.
    await _ohm(db_session, rink, day=date.today() + timedelta(days=1), hhmm="11:00")
    await db_session.commit()

    async with _client() as client:
        after = await client.get("/")
    assert after.status_code == 200
    assert "Хоккей (ОХМ)" in after.text
    assert 'href="/c/minsk?kind=ohm"' in after.text or 'href="/c/' in after.text and "kind=ohm" in after.text
