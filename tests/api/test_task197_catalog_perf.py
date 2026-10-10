"""TASK-197: one arena card does not scan the catalog; public lists cache, HTML does not."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.api.public_list_cache import PUBLIC_JSON_LIST_CACHE
from src.application.arena_public_use_cases import _ONE_ARENA_SQL
from src.application.ice_city_day import city_slug, invalidate_public_city_cache, resolve_city_by_ref
from src.application.selection_page import _WINDOW_SLOTS_PER_ARENA, _window_slots
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL
from tests.api.test_public_arenas import _add_future_session, _insert_city
from tests.api.test_public_place_page import _client, _place

# Cold /p/: cities, slug, card, media, sessions, freshness for this arena,
# the same window once more, then one catalog_consumer_events insert.
# Warm drops only the cached city list.
_PLACE_SQL_COLD = 8
_PLACE_SQL_WARM = 7

_CATALOG_WIDE_MARKERS = (
    "GROUP BY s.arena_id",
    "GROUP BY ta.arena_id",
    "GROUP BY tg.arena_id",
    "GROUP BY COALESCE(s.arena_id, t.primary_arena_id)",
)


def _count_sql(db_session):
    bind = db_session.sync_session.get_bind()
    counts = {"n": 0, "sql": []}

    def _before(conn, cursor, statement, parameters, context, executemany):
        sql = statement or ""
        head = sql.lstrip().upper()
        if head.startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1
            counts["sql"].append(" ".join(sql.split()))

    event.listen(bind, "before_cursor_execute", _before)
    return bind, counts, _before


def test_one_arena_sql_uses_the_shared_visibility_predicate() -> None:
    assert "a.id = :arena_id" in _ONE_ARENA_SQL
    assert PUBLIC_ARENA_VISIBLE_SQL in _ONE_ARENA_SQL
    for marker in _CATALOG_WIDE_MARKERS:
        assert marker not in _ONE_ARENA_SQL


@pytest.mark.asyncio
async def test_place_page_sql_does_not_scan_the_catalog(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    await _add_future_session(db_session, place["arena_id"], days_ahead=1, starts_at_local="19:30")
    await db_session.commit()

    bind, counts, before = _count_sql(db_session)
    try:
        async with _client() as client:
            first = await client.get(place["path"])
            cold = counts["n"]
            cold_sql = list(counts["sql"])
            counts["n"] = 0
            counts["sql"].clear()
            second = await client.get(place["path"])
            warm = counts["n"]
            warm_sql = list(counts["sql"])
    finally:
        event.remove(bind, "before_cursor_execute", before)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert cold == _PLACE_SQL_COLD, cold_sql
    assert warm == _PLACE_SQL_WARM, warm_sql
    for sql in cold_sql + warm_sql:
        for marker in _CATALOG_WIDE_MARKERS:
            assert marker not in sql
    assert any("a.id = " in sql and "created_by_trainer_id" in sql for sql in cold_sql)
    assert first.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_public_json_lists_are_cached_and_view_pages_are_not(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    await db_session.commit()
    slug = city_slug(place["city_name"])
    async with _client() as client:
        cities = await client.get("/api/public/cities")
        ice_cities = await client.get("/api/public/ice/cities")
        services = await client.get("/api/public/services")
        arenas = await client.get("/api/public/ice/arenas", params={"city_id": place["city_id"]})
        sessions = await client.get(f"/api/public/arenas/{place['arena_id']}/sessions")
        card = await client.get(f"/api/public/arenas/{place['arena_id']}")
        nearest = await client.get("/api/public/ice/nearest", params={"near": "53.9,27.56"})
        config = await client.get("/api/public/ice/map-config")
        selection = await client.get(f"/c/{slug}")
        today = await client.get(f"/ice/{slug}/today")
    for resp in (cities, ice_cities, services, arenas, sessions):
        assert resp.status_code == 200, resp.text
        assert resp.headers["cache-control"] == PUBLIC_JSON_LIST_CACHE
    assert card.status_code == 200
    assert card.headers["cache-control"] == "no-store"
    assert "no-store" in nearest.headers["cache-control"]
    assert config.headers["cache-control"] == "no-store"
    assert selection.status_code == 200
    assert selection.headers["cache-control"] == "private, no-store"
    assert today.status_code == 200
    assert today.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_city_cache_skips_the_second_read_and_drops_on_admin_rename(
    app_use_test_db, db_session, monkeypatch
) -> None:
    from src.api.miniapp_auth.deps import get_admin_miniapp_principal
    from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal

    name = f"Cachegrad{uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await db_session.commit()
    invalidate_public_city_cache()

    found = await resolve_city_by_ref(db_session, city_slug(name))
    assert found is not None and int(found["id"]) == city_id

    bind, counts, before = _count_sql(db_session)
    try:
        again = await resolve_city_by_ref(db_session, str(city_id))
        cached = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", before)
    assert again is not None and int(again["id"]) == city_id
    assert cached == 0

    new_name = name + "b"
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: MiniAppPrincipal(
        platform=MiniAppPlatform.TELEGRAM, user_id=4242
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patched = await client.patch(f"/api/webapp/admin/cities/{city_id}", json={"name": new_name})
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)
    assert patched.status_code == 200, patched.text
    assert await resolve_city_by_ref(db_session, city_slug(new_name)) is not None
    assert await resolve_city_by_ref(db_session, city_slug(name)) is None

    invalidate_public_city_cache()
    monkeypatch.setattr("src.application.ice_city_day.PUBLIC_CITY_CACHE_TTL_SEC", 0)
    await resolve_city_by_ref(db_session, str(city_id))
    bind, counts, before = _count_sql(db_session)
    try:
        await resolve_city_by_ref(db_session, str(city_id))
        expired = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", before)
    assert expired == 1


@pytest.mark.asyncio
async def test_selection_window_slots_cap_per_arena(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    start = datetime.now(timezone.utc) + timedelta(hours=2)
    for i in range(80):
        begins = start + timedelta(hours=i)
        ends = begins + timedelta(minutes=45)
        await db_session.execute(
            text("""
                INSERT INTO ice_sessions (
                    arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                    starts_at_local, ends_at_local, currency_code, status, schedule_basis
                )
                VALUES (
                    :aid, 'public_skate', :begins, :ends, :local_date,
                    :starts_local, :ends_local, 'BYN', 'active', 'live'
                )
                """),
            {
                "aid": place["arena_id"],
                "begins": begins,
                "ends": ends,
                "local_date": begins.date(),
                "starts_local": begins.time(),
                "ends_local": ends.time(),
            },
        )
    await db_session.commit()
    slots = await _window_slots(db_session, [place["arena_id"]], None, datetime.now(timezone.utc))
    got = slots[place["arena_id"]]
    assert len(got) == _WINDOW_SLOTS_PER_ARENA
    assert got[0]["id"] < got[-1]["id"]
