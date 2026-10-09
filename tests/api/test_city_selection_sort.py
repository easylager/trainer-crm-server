"""/c/{city}: места с будущими сеансами — первыми, остальные по алфавиту."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.ice_city_day import city_slug
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city

_NAME_RE = re.compile(r'<h2 class="pick__name"><a href="[^"]*">([^<]*)</a></h2>')


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False)


def _names(html: str) -> list[str]:
    return _NAME_RE.findall(html)


@pytest.mark.asyncio
async def test_city_page_puts_place_with_sessions_on_page_one(app_use_test_db, db_session) -> None:
    name = f"Сортск {uuid.uuid4().hex[:8]}"
    city_id = await _insert_city(db_session, name=name)
    plain = [f"Aa{i:02d} {uuid.uuid4().hex[:4]}" for i in range(12)]
    for place in plain:
        await _insert_arena(db_session, city_id, name=place)
    last = f"Яя {uuid.uuid4().hex[:4]}"
    last_id = await _insert_arena(db_session, city_id, name=last)
    await _add_future_session(db_session, last_id, days_ahead=1, starts_at_local="13:00")
    await db_session.commit()
    slug = city_slug(name)

    async with _client() as client:
        p1 = await client.get(f"/c/{slug}", params={"page": 1})
        p2 = await client.get(f"/c/{slug}", params={"page": 2})

    assert p1.status_code == 200
    assert p2.status_code == 200
    names1 = _names(p1.text)
    names2 = _names(p2.text)
    assert names1[0] == last, names1
    assert names1[1:] == plain[:11], names1
    assert names2 == plain[11:], names2


@pytest.mark.asyncio
async def test_city_page_orders_places_by_nearest_session(app_use_test_db, db_session) -> None:
    name = f"Сеансск {uuid.uuid4().hex[:8]}"
    city_id = await _insert_city(db_session, name=name)
    no_sessions = f"Aa00 {uuid.uuid4().hex[:4]}"
    await _insert_arena(db_session, city_id, name=no_sessions)
    late = f"Юю {uuid.uuid4().hex[:4]}"
    late_id = await _insert_arena(db_session, city_id, name=late)
    early = f"Яя {uuid.uuid4().hex[:4]}"
    early_id = await _insert_arena(db_session, city_id, name=early)
    await _add_future_session(db_session, late_id, days_ahead=3, starts_at_local="13:00")
    await _add_future_session(db_session, early_id, days_ahead=1, starts_at_local="13:00")
    await db_session.commit()
    slug = city_slug(name)

    async with _client() as client:
        page = await client.get(f"/c/{slug}", params={"page": 1})

    assert page.status_code == 200
    assert _names(page.text) == [early, late, no_sessions]
