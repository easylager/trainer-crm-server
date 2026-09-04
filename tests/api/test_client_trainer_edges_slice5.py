"""
EPIC1 Slice 5: client_trainer_edges is keyed by client_id, so a guardian/child profile gets
its own "мой тренер"/saved/notify-slots state instead of sharing the account's row.
See .ai/EPIC1-client-multi-profile.md.
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
    return 7_900_000_000 + (uuid.uuid4().int % 2_000_000_000)


async def _insert_client(db_session, *, telegram_id: int, first_name: str) -> int:
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
            VALUES (:fn, :tid, false)
            RETURNING id
            """
        ),
        {"fn": first_name, "tid": telegram_id},
    )
    client_id = int(r.scalar_one())
    await db_session.commit()
    return client_id


async def _add_child_profile(client, *, first_name: str) -> int:
    r = await client.post(
        "/api/webapp/client/profiles",
        json={"first_name": first_name},
        headers=_client_auth_headers(),
    )
    assert r.status_code == 200, r.text
    return r.json()["client_id"]


async def _seed_online_trainer(db_session) -> int:
    """Minimal trainer row — trainer-edges endpoints don't require booking capability, only trainers.id."""
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.commit()
    return int(trainer_id)


@pytest.mark.asyncio
async def test_save_trainer_is_isolated_per_profile(app_use_test_db, db_session) -> None:
    """Saving a trainer as the child must not make it appear saved for the parent, or vice versa."""
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Мама")
    trainer_id = await _seed_online_trainer(db_session)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Сын")

            r_save_child = await client.post(
                "/api/webapp/client/trainer-edges/save",
                json={"trainer_id": trainer_id},
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
            assert r_save_child.status_code == 200, r_save_child.text

            r_edges_parent = await client.get(
                "/api/webapp/client/trainer-edges", headers=_client_auth_headers()
            )
            r_edges_child = await client.get(
                "/api/webapp/client/trainer-edges",
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )

    assert r_edges_parent.status_code == 200 and r_edges_child.status_code == 200
    assert r_edges_parent.json()["all"] == []
    # Sole saved edge with no other candidate is auto-derived as primary rather than listed
    # under "saved" (compute_primary_edge) — "all" is the profile-agnostic source of truth here.
    child_all_ids = {e["trainer_id"] for e in r_edges_child.json()["all"]}
    assert child_all_ids == {trainer_id}
    child_edge = next(e for e in r_edges_child.json()["all"] if e["trainer_id"] == trainer_id)
    assert child_edge["is_saved"] is True


@pytest.mark.asyncio
async def test_set_primary_trainer_is_isolated_per_profile(app_use_test_db, db_session) -> None:
    """Each profile can have a different primary trainer under the same account."""
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Папа")
    trainer_parent = await _seed_online_trainer(db_session)
    trainer_child = await _seed_online_trainer(db_session)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Дочь")

            r_parent_primary = await client.post(
                "/api/webapp/client/trainer-edges/primary",
                json={"trainer_id": trainer_parent},
                headers=_client_auth_headers(),
            )
            assert r_parent_primary.status_code == 200, r_parent_primary.text

            r_child_primary = await client.post(
                "/api/webapp/client/trainer-edges/primary",
                json={"trainer_id": trainer_child},
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
            assert r_child_primary.status_code == 200, r_child_primary.text

            r_edges_parent = await client.get(
                "/api/webapp/client/trainer-edges", headers=_client_auth_headers()
            )
            r_edges_child = await client.get(
                "/api/webapp/client/trainer-edges",
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )

    assert r_edges_parent.json()["primary"]["trainer_id"] == trainer_parent
    assert r_edges_child.json()["primary"]["trainer_id"] == trainer_child


@pytest.mark.asyncio
async def test_notify_slots_subscription_is_isolated_per_profile(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Опекун")
    trainer_id = await _seed_online_trainer(db_session)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Ребёнок")

            r = await client.post(
                "/api/webapp/client/trainer-edges/notify-slots",
                json={"trainer_id": trainer_id},
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
            assert r.status_code == 200, r.text
            assert r.json()["edge"]["notify_when_slots"] is True

    r_child = await db_session.execute(
        text("SELECT notify_when_slots FROM client_trainer_edges WHERE client_id = :cid AND trainer_id = :tid"),
        {"cid": child_id, "tid": trainer_id},
    )
    assert r_child.scalar_one() is True
    r_parent = await db_session.execute(
        text("SELECT COUNT(*) FROM client_trainer_edges WHERE telegram_id = :tg AND trainer_id = :tid AND client_id != :cid"),
        {"tg": tid, "tid": trainer_id, "cid": child_id},
    )
    assert r_parent.scalar_one() == 0


@pytest.mark.asyncio
async def test_trainer_edge_write_requires_registration(app_use_test_db, db_session) -> None:
    """No clients row yet for this Telegram account -> clear 400, not a silently orphaned edge row."""
    tid = _fresh_client_telegram_id()
    trainer_id = await _seed_online_trainer(db_session)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/webapp/client/trainer-edges/save",
                json={"trainer_id": trainer_id},
                headers=_client_auth_headers(),
            )
    assert r.status_code == 400
