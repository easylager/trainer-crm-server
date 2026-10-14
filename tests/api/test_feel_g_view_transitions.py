"""FEEL-G: cross-document view transitions on public catalog pages."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city

REPO = Path(__file__).resolve().parents[2]
STYLE_B = (REPO / "static/share/style-b.css").read_text(encoding="utf-8")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_style_b_declares_cross_document_navigation() -> None:
    assert "@view-transition" in STYLE_B and "navigation: auto" in STYLE_B
    assert "prefers-reduced-motion: reduce" in STYLE_B
    assert "navigation: none" in STYLE_B
    assert "vt-when-strip" in STYLE_B
    assert "glide-when-strip" in STYLE_B


@pytest.mark.asyncio
async def test_home_when_strip_has_view_transition_name(app_use_test_db, db_session) -> None:
    name = f"VT {uuid.uuid4().hex[:6]}"
    await _insert_city(db_session, name=name)
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/?when=today")
    assert home.status_code == 200
    assert 'class="b-when vt-when-strip"' in home.text
    assert 'aria-label="Когда"' in home.text


@pytest.mark.asyncio
async def test_ice_list_and_place_share_session_time_vt_name(app_use_test_db, db_session) -> None:
    name = f"VT ice {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток VT")
    day = datetime.now(ZoneInfo("Europe/Minsk")).date()
    session_id = await create_ice_session(
        db_session,
        arena_id,
        local_date=day,
        starts_at_local="10:15",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=1000,
        price_child_minor=None,
        price_rental_minor=None,
    )
    slug_row = await db_session.execute(
        text("SELECT slug FROM arena_profiles WHERE arena_id = :id"),
        {"id": arena_id},
    )
    place_slug = str(slug_row.scalar_one())
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    vt = f"glide-s-{arena_id}-t1015"

    async with _client() as client:
        listing = await client.get(f"/c/{slug}?t=ice&w=today")
        place = await client.get(f"/p/{slug}/{place_slug}?s={session_id}")

    assert listing.status_code == 200
    assert place.status_code == 200
    assert "vt-when-strip" in listing.text
    assert f"view-transition-name: {vt}" in listing.text
    assert f"view-transition-name: {vt}" in place.text
    assert len(re.findall(rf"view-transition-name: {vt}", listing.text)) == 1
    assert len(re.findall(rf"view-transition-name: {vt}", place.text)) == 1
