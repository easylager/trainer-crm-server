"""TASK-143 (S2): GET /api/public/collectives/{slug} echoes the school's площадка."""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.arena_profile import backfill_arena_profiles
from tests.api.collective_api_helpers import seed_active_collective_owner
from tests.api.test_webapp_client_miniapp_integration import _require_seed_ids

pytestmark = pytest.mark.collective


async def _insert_public_arena(db_session, *, city_id: int, name: str) -> int:
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'ул. Тестовая, 5', true, true)
            RETURNING id
            """
        ),
        {"cid": city_id, "name": name},
    )
    arena_id = int(ins.scalar_one())
    await backfill_arena_profiles(db_session)
    await db_session.flush()
    return arena_id


@pytest.mark.asyncio
async def test_public_collective_shows_primary_arena_when_set(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_tr = await client.post(
            "/api/trainers",
            json={
                "profile": {"first_name": "Pub", "last_name": "Arena", "age": 30, "city_id": cid},
                "service_ids": [sid],
            },
        )
        assert r_tr.status_code == 200
        tid = r_tr.json()["id"]
    slug = f"pub-arena-{uuid.uuid4().hex[:8]}"
    arena_name = "Ледовый дворец Публичный"
    arena_id = await _insert_public_arena(db_session, city_id=cid, name=arena_name)
    collective_id = await seed_active_collective_owner(db_session, tid, slug=slug)
    await db_session.execute(
        text("UPDATE collectives SET primary_arena_id = :aid WHERE id = :cid"),
        {"aid": arena_id, "cid": collective_id},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/public/collectives/{slug}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary_arena_id"] == arena_id
    assert body["primary_arena_name"] == arena_name
    assert body["primary_arena_address"] == "ул. Тестовая, 5"


@pytest.mark.asyncio
async def test_public_collective_hides_arena_fields_when_not_set(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_tr = await client.post(
            "/api/trainers",
            json={
                "profile": {"first_name": "Pub", "last_name": "NoArena", "age": 30, "city_id": cid},
                "service_ids": [sid],
            },
        )
        assert r_tr.status_code == 200
        tid = r_tr.json()["id"]
    slug = f"pub-noarena-{uuid.uuid4().hex[:8]}"
    await seed_active_collective_owner(db_session, tid, slug=slug)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/public/collectives/{slug}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary_arena_id"] is None
    assert body["primary_arena_name"] is None
    assert body["primary_arena_address"] is None
