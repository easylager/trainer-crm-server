"""Client ice watches + watches hub API."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.test_webapp_client_miniapp_integration import (
    _client_auth_headers,
    patch_client_init_auth,
)


def _fresh_client_telegram_id() -> int:
    return 7_800_000_000 + (uuid.uuid4().int % 2_000_000_000)


async def _insert_client(db_session, *, telegram_id: int) -> int:
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state)
            VALUES (:tid, 'idle')
            ON CONFLICT (telegram_id) DO NOTHING
            """
        ),
        {"tid": telegram_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, telegram_id, is_sandbox)
            VALUES ('Watch', :tid, false)
            RETURNING id
            """
        ),
        {"tid": telegram_id},
    )
    client_id = int(r.scalar_one())
    await db_session.commit()
    return client_id


@pytest.mark.asyncio
async def test_ice_watch_subscribe_list_unsubscribe(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid)
    city_id = int((await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar_one())
    arena = (
        await db_session.execute(
            text(
                """
                INSERT INTO arenas (city_id, name, latitude, longitude, is_active, is_confirmed, venue_type)
                VALUES (:cid, 'Watch Test Rink', 53.9, 27.5, true, true, 'ice')
                RETURNING id
                """
            ),
            {"cid": city_id},
        )
    ).scalar_one()
    await db_session.commit()

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            post = await client.post(
                "/api/webapp/client/ice-watches",
                headers=_client_auth_headers(),
                json={"arena_id": int(arena), "watch_kind": "sessions", "when": "weekend"},
            )
            assert post.status_code == 200, post.text
            wid = post.json()["watch"]["id"]

            hub = await client.get("/api/webapp/client/watches", headers=_client_auth_headers())
            assert hub.status_code == 200
            body = hub.json()
            assert body["active_count"] >= 1
            assert body["ice_watches"] == 1
            assert len(body["ice_watch_items"]) == 1

            delete = await client.delete(
                f"/api/webapp/client/ice-watches/{wid}",
                headers=_client_auth_headers(),
            )
            assert delete.status_code == 200

            hub2 = await client.get("/api/webapp/client/watches", headers=_client_auth_headers())
            assert hub2.json()["ice_watches"] == 0
