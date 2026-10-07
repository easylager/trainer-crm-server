"""TASK-191-B: город целиком, пагинация, фильтры, demand CTA."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.application.ice_city_day import city_slug
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL
from tests.api.test_catalog_shops import _admin_create_shop
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False)


@pytest.mark.asyncio
async def test_city_page_lists_all_venue_types_with_pagination(app_use_test_db, db_session) -> None:
    name = f"Пагинск {uuid.uuid4().hex[:8]}"
    city_id = await _insert_city(db_session, name=name)
    ids = []
    for i in range(14):
        ids.append(await _insert_arena(db_session, city_id, name=f"Каток {i} {uuid.uuid4().hex[:3]}"))
    await _admin_create_shop(city_id, f"Магаз {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        p1 = await client.get(f"/c/{slug}")
        p2 = await client.get(f"/c/{slug}", params={"page": 2})
        shops = await client.get(f"/c/{slug}", params={"t": "shop"})
    assert p1.status_code == 200
    assert p2.status_code == 200
    assert 'rel="next"' in p1.text or "Дальше" in p1.text
    assert 'name="robots" content="noindex, follow"' in p2.text
    assert "Магазины" in p1.text or "магазин" in shops.text.lower()
    assert shops.status_code == 200


@pytest.mark.asyncio
async def test_city_page_sql_budget_stable(app_use_test_db, db_session) -> None:
    name = f"Перфск {uuid.uuid4().hex[:8]}"
    city_id = await _insert_city(db_session, name=name)
    for i in range(5):
        await _insert_arena(db_session, city_id, name=f"A{i} {uuid.uuid4().hex[:3]}")
    await db_session.commit()
    slug = city_slug(name)
    bind = db_session.sync_session.get_bind()
    counts: dict[str, int] = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        sql = (statement or "").lstrip().upper()
        if sql.startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    try:
        async with _client() as client:
            small = await client.get(f"/c/{slug}")
        n_small = counts["n"]
        for i in range(10):
            await _insert_arena(db_session, city_id, name=f"B{i} {uuid.uuid4().hex[:3]}")
        await db_session.commit()
        counts["n"] = 0
        async with _client() as client:
            big = await client.get(f"/c/{slug}")
        n_big = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", _before)
    assert small.status_code == 200 and big.status_code == 200
    assert abs(n_big - n_small) <= 1, (n_small, n_big)
    assert PUBLIC_ARENA_VISIBLE_SQL  # import used in module under test


@pytest.mark.asyncio
async def test_outbound_contact_click_records_event(app_use_test_db, db_session, monkeypatch) -> None:
    from starlette.requests import Request

    from src.api.routes.catalog_consumer_telemetry import public_outbound_redirect

    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "x" * 32)
    name = f"Кликск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    aid = await _insert_arena(db_session, city_id, name="С телефоном")
    await db_session.execute(
        text("UPDATE arena_profiles SET phone = '+375291234567' WHERE arena_id = :id"),
        {"id": aid},
    )
    await db_session.commit()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/public/catalog/outbound",
        "headers": [(b"user-agent", b"Mozilla/5.0")],
        "query_string": b"",
    }
    request = Request(scope)
    resp = await public_outbound_redirect(
        request,
        action="phone",
        surface="place_page",
        city_id=city_id,
        arena_id=aid,
        session=db_session,
    )
    assert resp.status_code == 302
    assert str(resp.headers.get("location") or "").startswith("tel:")
    row = (
        await db_session.execute(
            text(
                "SELECT kind, payload->>'action' FROM catalog_consumer_events "
                "WHERE arena_id = :a ORDER BY id DESC LIMIT 1"
            ),
            {"a": aid},
        )
    ).first()
    assert row and row[0] == "public_contact_click" and row[1] == "phone"
