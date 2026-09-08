"""
EPIC1 Slice 3: GET/POST /api/webapp/client/profiles + PATCH .../default.

See docs/epics/client-multi-profile.md.
"""
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
    return 7_500_000_000 + (uuid.uuid4().int % 2_000_000_000)


async def _insert_client(db_session, *, telegram_id: int, first_name: str = "Родитель") -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, telegram_id, is_sandbox)
            VALUES (:fn, :tid, false)
            RETURNING id
            """
        ),
        {"fn": first_name, "tid": telegram_id},
    )
    client_id = int(r.scalar_one())
    await db_session.commit()
    return client_id


@pytest.mark.asyncio
async def test_get_profiles_returns_self_only_for_a_plain_account(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/webapp/client/profiles", headers=_client_auth_headers())

    assert r.status_code == 200
    body = r.json()
    assert body["default_profile_id"] == client_id
    assert [p["client_id"] for p in body["items"]] == [client_id]
    assert body["items"][0]["role"] == "self"


@pytest.mark.asyncio
async def test_get_profiles_empty_for_account_with_no_client_row(app_use_test_db, db_session) -> None:
    """A brand-new Telegram user with no bookings yet has no profiles to switch between."""
    tid = _fresh_client_telegram_id()
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/webapp/client/profiles", headers=_client_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["default_profile_id"] is None


@pytest.mark.asyncio
async def test_post_profiles_creates_child_and_get_lists_both(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_create = await client.post(
                "/api/webapp/client/profiles",
                json={"first_name": "Ваня", "last_name": "Иванов"},
                headers=_client_auth_headers(),
            )
            assert r_create.status_code == 200
            child_id = r_create.json()["client_id"]
            assert child_id != parent_id

            r_list = await client.get("/api/webapp/client/profiles", headers=_client_auth_headers())

    body = r_list.json()
    ids = {p["client_id"]: p for p in body["items"]}
    assert set(ids) == {parent_id, child_id}
    assert ids[parent_id]["role"] == "self"
    assert ids[child_id]["role"] == "guardian"
    assert body["default_profile_id"] == parent_id


@pytest.mark.asyncio
async def test_post_profiles_requires_non_empty_first_name(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/webapp/client/profiles",
                json={"first_name": ""},
                headers=_client_auth_headers(),
            )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_default_switches_and_rejects_foreign_profile(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Папа")
    other_tid = _fresh_client_telegram_id()
    other_client_id = await _insert_client(db_session, telegram_id=other_tid, first_name="Чужой")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_create = await client.post(
                "/api/webapp/client/profiles",
                json={"first_name": "Сын"},
                headers=_client_auth_headers(),
            )
            child_id = r_create.json()["client_id"]

            r_switch = await client.patch(
                f"/api/webapp/client/profiles/{child_id}/default", headers=_client_auth_headers()
            )
            assert r_switch.status_code == 200

            r_list = await client.get("/api/webapp/client/profiles", headers=_client_auth_headers())
            assert r_list.json()["default_profile_id"] == child_id

            r_foreign = await client.patch(
                f"/api/webapp/client/profiles/{other_client_id}/default", headers=_client_auth_headers()
            )
            assert r_foreign.status_code == 404
