"""TASK-253: «Позвать» на плитке списка и endpoint подборки в разметке."""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.ice_city_day import city_slug
from tests.api.test_ice_windows_and_nearest import _session
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _card_block(html: str, arena_name: str) -> str:
    for block in re.findall(r'<article class="b-card2">.*?</article>', html, re.DOTALL):
        if arena_name in block:
            return block
    raise AssertionError(f"card for {arena_name!r} missing")


@pytest.mark.asyncio
async def test_selection_tile_invite_when_session(app_use_test_db, db_session) -> None:
    name = f"Зовск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink_name = f"Каток {uuid.uuid4().hex[:4]}"
    rink_id = await _insert_arena(db_session, city_id, name=rink_name)
    await _session(db_session, rink_id, day=date.today() + timedelta(days=1), hhmm="09:00")
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/c/{slug}", params={"t": "ice"})
    assert page.status_code == 200
    block = _card_block(page.text, rink_name)
    assert "Позвать" in block
    assert "data-invite-session=" in block
    assert f'href="/p/{slug}/' in block and "?s=" in block
    assert "catalog-list-share.js" in page.text
    assert "data-catalog-selection-share=" in page.text
    assert f"city_id={city_id}" in page.text
    assert "venue_type=ice" in page.text


@pytest.mark.asyncio
async def test_selection_tile_no_invite_without_session(app_use_test_db, db_session) -> None:
    name = f"Пустой {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink_name = f"Без льда {uuid.uuid4().hex[:4]}"
    await _insert_arena(db_session, city_id, name=rink_name)
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/c/{slug}", params={"t": "ice"})
    assert page.status_code == 200
    assert rink_name in page.text
    assert "b-slot--invite" not in page.text
    assert "data-invite-arena=" not in page.text


@pytest.mark.asyncio
async def test_selection_share_endpoint_api(app_use_test_db, db_session) -> None:
    name = f"Шер {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name=f"Лёд {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/c/{slug}", params={"t": "ice", "w": "tomorrow"})
        api = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": city_id, "venue_type": "ice", "when": "tomorrow", "record": "false"},
        )
    assert page.status_code == 200
    assert "when=tomorrow" in page.text
    assert api.status_code == 200
    assert api.json().get("share_url")


@pytest.mark.asyncio
async def test_selection_dual_share_markup_and_css_toggle(app_use_test_db, db_session) -> None:
    """SSR: кнопка подборки и legacy share_html; CSS переключает видимость с html.js."""
    name = f"Два {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink_id = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await _session(db_session, rink_id, day=date.today() + timedelta(days=1), hhmm="09:00")
    await db_session.commit()
    slug = city_slug(name)
    css_path = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "static"
        / "share"
        / "catalog-list-share.css"
    )
    css = css_path.read_text(encoding="utf-8")
    async with _client() as client:
        page = await client.get(f"/c/{slug}", params={"t": "ice"})
    assert page.status_code == 200
    html = page.text
    assert 'class="b-sec b-sec--share-pick"' in html
    assert "Поделиться подборкой" in html
    assert 'class="b-share"' in html
    assert "share__row" in html
    assert "catalog-list-share.css" in html
    assert ".b-sec--share-pick" in css and "display: none" in css
    assert "html.js .b-sec--share-pick" in css
    assert re.search(r"html\.js \.b-share\s*\{[^}]*display:\s*none", css)

