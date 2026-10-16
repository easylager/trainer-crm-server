"""FEEL-G: cross-document view transitions on public catalog pages."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
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
_GLIDE_S_VT = re.compile(r"view-transition-name:\s*glide-s-\d+")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_style_b_declares_cross_document_navigation() -> None:
    assert "@view-transition" in STYLE_B and "navigation: auto" in STYLE_B
    assert "prefers-reduced-motion: reduce" in STYLE_B
    assert "navigation: none" in STYLE_B
    assert "vt-when-strip" in STYLE_B
    assert "glide-when-strip" in STYLE_B
    assert "glide-when-thumb" in STYLE_B
    assert "html::view-transition-old(root)" not in STYLE_B


@pytest.mark.asyncio
async def test_home_when_strip_has_view_transition_name(app_use_test_db, db_session) -> None:
    name = f"VT {uuid.uuid4().hex[:6]}"
    await _insert_city(db_session, name=name)
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/?when=today")
        tomorrow = await client.get("/?when=tomorrow")
    assert home.status_code == 200
    assert 'class="b-when vt-when-strip"' in home.text
    assert 'style="--when-i: 0"' in home.text
    assert 'class="b-when__thumb"' in home.text
    assert 'aria-label="Когда"' in home.text
    assert tomorrow.status_code == 200
    assert 'style="--when-i: 1"' in tomorrow.text


@pytest.mark.asyncio
async def test_ice_list_and_place_share_session_time_vt_by_session_id(
    app_use_test_db, db_session
) -> None:
    name = f"VT ice {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток VT")
    # Завтра, а не сегодня: сеанс «сегодня в 10:15» после 10:15 по Минску уже в прошлом.
    day = datetime.now(ZoneInfo("Europe/Minsk")).date() + timedelta(days=1)
    session_row = await create_ice_session(
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
    session_id = int(session_row["id"])
    slug_row = await db_session.execute(
        text("SELECT slug FROM arena_profiles WHERE arena_id = :id"),
        {"id": arena_id},
    )
    place_slug = str(slug_row.scalar_one())
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    vt = f"glide-s-{session_id}"

    async with _client() as client:
        listing = await client.get(f"/c/{slug}?t=ice&w=tomorrow")
        place = await client.get(f"/p/{slug}/{place_slug}?s={session_id}")

    assert listing.status_code == 200
    assert place.status_code == 200
    assert f"view-transition-name: {vt}" in listing.text
    assert f"view-transition-name: {vt}" in place.text
    assert len(re.findall(rf"view-transition-name: {vt}", listing.text)) == 1
    assert len(re.findall(rf"view-transition-name: {vt}", place.text)) == 1


@pytest.mark.asyncio
async def test_place_at_most_one_session_vt_name_when_same_clock_on_many_days(
    app_use_test_db, db_session
) -> None:
    name = f"VT multi {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток multi")
    tz = ZoneInfo("Europe/Minsk")
    base = datetime.now(tz).date()
    ids: list[int] = []
    for offset in (0, 1, 2):
        row = await create_ice_session(
            db_session,
            arena_id,
            local_date=base + timedelta(days=offset),
            starts_at_local="10:00",
            duration_minutes=60,
            kind="public_skate",
            price_adult_minor=1000,
            price_child_minor=None,
            price_rental_minor=None,
        )
        ids.append(int(row["id"]))
    slug_row = await db_session.execute(
        text("SELECT slug FROM arena_profiles WHERE arena_id = :id"),
        {"id": arena_id},
    )
    place_slug = str(slug_row.scalar_one())
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    pick = ids[1]

    async with _client() as client:
        place = await client.get(f"/p/{slug}/{place_slug}?s={pick}")

    assert place.status_code == 200
    names = _GLIDE_S_VT.findall(place.text)
    assert len(names) == 1
    assert f"glide-s-{pick}" in names[0]


@pytest.mark.asyncio
async def test_weekend_list_session_vt_names_are_unique(app_use_test_db, db_session) -> None:
    name = f"VT wknd {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток wknd")
    tz = ZoneInfo("Europe/Minsk")
    today = datetime.now(tz).date()
    days_until_sat = (5 - today.weekday()) % 7
    if days_until_sat == 0 and datetime.now(tz).hour >= 21:
        days_until_sat = 7
    sat = today + timedelta(days=days_until_sat or 7)
    ids: list[int] = []
    for i, clock in enumerate(("11:00", "14:30")):
        row = await create_ice_session(
            db_session,
            arena_id,
            local_date=sat + timedelta(days=i),
            starts_at_local=clock,
            duration_minutes=60,
            kind="public_skate",
            price_adult_minor=1000,
            price_child_minor=None,
            price_rental_minor=None,
        )
        ids.append(int(row["id"]))
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        listing = await client.get(f"/c/{slug}?t=ice&w=weekend")

    assert listing.status_code == 200
    names = _GLIDE_S_VT.findall(listing.text)
    assert len(names) >= 2
    assert len(names) == len(set(names))
