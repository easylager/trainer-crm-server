"""TASK-278 (вариант A): «Открыть в Telegram» плашкой внизу каждой страницы, под ней — строка про карту."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug
from src.application.style_b import city_map_hint, telegram_dock_html
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _dock(html: str) -> str:
    match = re.search(r'<nav class="b-tgdock tg-out"[^>]*>(.*?)</nav>', html, re.S)
    assert match, "нет плашки Telegram"
    return match.group(1)


def test_city_map_hint_counts_only_when_every_rink_is_on_the_map() -> None:
    rink = {"venue_type": "ice", "latitude": 53.9, "longitude": 27.5}
    shop = {"venue_type": "shop", "latitude": None, "longitude": None}
    assert city_map_hint([rink, rink, shop]) == "там все 2 катка на карте"
    assert city_map_hint([rink] * 10) == "там все 10 катков на карте"
    assert city_map_hint([rink]) == "там этот каток на карте"
    # Хоть один каток без координат — числа нет, обещание общее.
    assert city_map_hint([rink, {"venue_type": "ice", "latitude": None, "longitude": 1}]) == "там карта всех катков"
    assert city_map_hint([]) == "там карта всех катков"


def test_dock_needs_a_link() -> None:
    assert telegram_dock_html(None, hint="x") == ""
    dock = telegram_dock_html("/api/public/catalog/open-telegram?startapp=catalog", hint="там карта всех катков")
    assert "Открыть в Telegram" in dock and "там карта всех катков" in dock


@pytest.mark.asyncio
async def test_city_page_has_the_dock_and_no_second_telegram_button(app_use_test_db, db_session) -> None:
    name = f"Докск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    async with _client() as client:
        html = (await client.get(f"/c/{city_slug(name)}")).text
    dock = _dock(html)
    assert "open-telegram?startapp=catalog_" in dock
    assert "там все 2 катка на карте" in dock
    assert "b-share__bot" not in html
    assert html.count('class="b-tgbtn tg-out"') == 1


@pytest.mark.asyncio
async def test_city_without_coordinates_promises_no_number(app_use_test_db, db_session) -> None:
    name = f"Безкоордск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    aid = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await db_session.execute(text("UPDATE arenas SET latitude = NULL WHERE id = :id"), {"id": aid})
    await db_session.commit()
    async with _client() as client:
        html = (await client.get(f"/c/{city_slug(name)}")).text
    assert "там карта всех катков" in _dock(html)


@pytest.mark.asyncio
async def test_home_and_list_pages_have_the_dock(app_use_test_db, db_session) -> None:
    name = f"Спискск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    async with _client() as client:
        home = (await client.get("/")).text
        listing = (await client.get(f"/c/{city_slug(name)}", params={"t": "ice"})).text
    assert "tg-dock.js" in home
    assert "там карта всех катков" in _dock(home)
    assert "там все катки города на карте" in _dock(listing)
    assert "b-share__bot" not in listing
