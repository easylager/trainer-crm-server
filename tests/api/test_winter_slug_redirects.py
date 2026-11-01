"""301 со старых slug зимних точек: переименование типа и слияние дублей (TASK-343)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application import arena_slug_redirects as red
from src.application import winter_admin as wa
from src.application.ice_city_day import city_slug
from tests.api.test_public_arenas import _insert_arena, _insert_city

NOW = datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _slug(db, arena_id):
    return (await db.execute(text("SELECT slug FROM arena_profiles WHERE arena_id=:a"), {"a": arena_id})).scalar_one()


async def _make_seasonal(db, arena_id):
    await db.execute(text("INSERT INTO seasonal_rinks (arena_id, kind) VALUES (:a, 'rink')"), {"a": arena_id})
    await db.execute(
        text("INSERT INTO seasonal_rink_seasons (arena_id, season, state) VALUES (:a, 2026, 'waiting')"), {"a": arena_id})


@pytest.mark.asyncio
async def test_old_slug_after_merge_and_rename_answers_301(app_use_test_db, db_session) -> None:
    city_name = f"Зимоград {uuid.uuid4().hex[:6]}"
    city = await _insert_city(db_session, name=city_name)
    keep = await _insert_arena(db_session, city, name="Коробка основная")
    dup = await _insert_arena(db_session, city, name="Коробка дубль")
    for a in (keep, dup):
        await _make_seasonal(db_session, a)
    keep_slug, dup_slug = await _slug(db_session, keep), await _slug(db_session, dup)
    await wa.merge_points(db_session, dup, keep, admin_id=1, now=NOW)
    await wa.rename_point(db_session, keep, kind="hockey_box", admin_id=1, now=NOW)
    new_slug = await _slug(db_session, keep)
    assert new_slug != keep_slug
    await db_session.commit()
    base = f"/p/{city_slug(city_name)}"
    async with _client() as client:
        renamed = await client.get(f"{base}/{keep_slug}?s=3", follow_redirects=False)
        merged = await client.get(f"{base}/{dup_slug}", follow_redirects=False)
        unknown = await client.get(f"{base}/never-existed", follow_redirects=False)
    assert renamed.status_code == 301 and renamed.headers["location"] == f"{base}/{new_slug}?s=3"
    assert merged.status_code == 301 and merged.headers["location"] == f"{base}/{new_slug}"
    assert unknown.status_code == 404
    assert await red.lookup_redirect(db_session, city, dup_slug) == keep
