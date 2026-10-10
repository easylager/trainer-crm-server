"""Чип «Заточка и прокат» в ленте мини-аппа: ?svc=service и service_count."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_svc_service_keeps_places_with_sharpening_or_rental(app_use_test_db, db_session) -> None:
    name = f"SvcChip {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    sharp = await _insert_arena(db_session, city_id, name=f"Заточка {uuid.uuid4().hex[:4]}")
    plain = await _insert_arena(db_session, city_id, name=f"Просто лёд {uuid.uuid4().hex[:4]}")
    shop = await _insert_arena(db_session, city_id, name=f"Магазин {uuid.uuid4().hex[:4]}")
    await db_session.execute(
        text("UPDATE arenas SET venue_type = 'shop' WHERE id = :id"),
        {"id": shop},
    )
    await db_session.execute(
        text("UPDATE arena_profiles SET amenities = CAST(:a AS jsonb) WHERE arena_id = :id"),
        {"id": sharp, "a": json.dumps({"skate_sharpening": True})},
    )
    await db_session.execute(
        text("UPDATE arena_profiles SET amenities = CAST(:a AS jsonb) WHERE arena_id = :id"),
        {"id": shop, "a": json.dumps({"skate_rental": True})},
    )
    await db_session.commit()

    async with _client() as client:
        plain_list = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": city_id, "intent": "skate", "limit": 50},
        )
        filtered = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": city_id, "intent": "skate", "limit": 50, "svc": "service"},
        )

    assert plain_list.status_code == 200
    body = plain_list.json()
    ids = {int(i["id"]) for i in body["items"]}
    assert sharp in ids and plain in ids
    assert shop not in ids
    assert int(body["service_count"]) == 1

    assert filtered.status_code == 200
    filtered_ids = {int(i["id"]) for i in filtered.json()["items"]}
    assert filtered_ids == {sharp}
    assert int(filtered.json()["service_count"]) == 1
