"""
EPIC1 Slice 4: existing client endpoints resolve the acting client via ``X-Profile-Id``
instead of always the account's own row. See .ai/EPIC1-client-multi-profile.md.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.test_webapp_client_miniapp_integration import (
    _client_auth_headers,
    _require_seed_ids,
    patch_client_init_auth,
)


def _fresh_client_telegram_id() -> int:
    return 7_800_000_000 + (uuid.uuid4().int % 2_000_000_000)


async def _insert_client(db_session, *, telegram_id: int | None, first_name: str) -> int:
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


async def _seed_pass(db_session, *, trainer_id: int, client_id: int) -> None:
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active)
            VALUES (:tid, 'Pack', 8, 8000, true) RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (pass_product_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status)
            VALUES (:cid, :pid, 5, 8, 8000, 'active')
            """
        ),
        {"cid": client_id, "pid": pass_product_id},
    )
    await db_session.commit()


async def _seed_trainer(db_session) -> int:
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.commit()
    return int(trainer_id)


@pytest.mark.asyncio
async def test_get_client_passes_scoped_by_x_profile_id(app_use_test_db, db_session) -> None:
    """A parent's ``GET /client/passes`` must not leak into the child profile's list, and vice versa."""
    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")
    trainer_id = await _seed_trainer(db_session)
    await _seed_pass(db_session, trainer_id=trainer_id, client_id=parent_id)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Сын")

    await _seed_pass(db_session, trainer_id=trainer_id, client_id=child_id)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_parent = await client.get("/api/webapp/client/passes", headers=_client_auth_headers())
            r_child = await client.get(
                "/api/webapp/client/passes",
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )

    assert r_parent.status_code == 200 and r_child.status_code == 200
    parent_pass_ids = {p["id"] if "id" in p else None for p in r_parent.json()["items"]}
    child_items = r_child.json()["items"]
    assert len(child_items) == 1
    assert len(r_parent.json()["items"]) == 1
    # Different underlying pass_instances rows — the two lists must not be identical.
    assert child_items[0] != r_parent.json()["items"][0]


@pytest.mark.asyncio
async def test_post_client_request_attributed_to_requested_profile(app_use_test_db, db_session) -> None:
    """Creating a request while the child profile is selected must file it under the child, not the parent."""
    sid, cid, _aid = await _require_seed_ids(db_session)
    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Папа")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Дочь")

            cr = await client.post(
                "/api/webapp/client/request",
                json={"city_id": cid, "service_id": sid, "comment": "для ребёнка"},
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
    assert cr.status_code == 200, cr.text
    request_id = cr.json()["request_id"]

    r = await db_session.execute(
        text("SELECT client_id FROM client_requests WHERE id = :rid"), {"rid": request_id}
    )
    owner_client_id = r.scalar_one()
    assert owner_client_id == child_id
    assert owner_client_id != parent_id


@pytest.mark.asyncio
async def test_patch_client_request_respects_selected_profile_ownership(app_use_test_db, db_session) -> None:
    """PATCH on a child's request without X-Profile-Id (defaulting to the parent) must not succeed."""
    sid, cid, _aid = await _require_seed_ids(db_session)
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Сын")

            cr = await client.post(
                "/api/webapp/client/request",
                json={"city_id": cid, "service_id": sid, "comment": "исходно"},
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
            request_id = cr.json()["request_id"]

            # Same account, but no X-Profile-Id header -> resolves to the parent's own row,
            # which does not own this request.
            r_as_parent = await client.patch(
                f"/api/webapp/client/requests/{request_id}",
                json={"comment": "подменено родителем"},
                headers=_client_auth_headers(),
            )
            assert r_as_parent.status_code == 404

            r_as_child = await client.patch(
                f"/api/webapp/client/requests/{request_id}",
                json={"comment": "обновлено ребёнком"},
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
            assert r_as_child.status_code == 200, r_as_child.text


@pytest.mark.asyncio
async def test_malformed_x_profile_id_header_falls_back_silently(app_use_test_db, db_session) -> None:
    """A stale/garbage X-Profile-Id must never 422/500 — it degrades to the account's own profile."""
    tid = _fresh_client_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid, first_name="Клиент")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/webapp/client/activity-stats",
                headers={**_client_auth_headers(), "X-Profile-Id": "not-a-number"},
            )
    assert r.status_code == 200, r.text

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r2 = await client.get(
                "/api/webapp/client/activity-stats",
                headers={**_client_auth_headers(), "X-Profile-Id": "999999999"},
            )
    assert r2.status_code == 200, r2.text
