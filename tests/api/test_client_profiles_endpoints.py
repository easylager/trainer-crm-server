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


@pytest.mark.asyncio
async def test_post_profiles_same_child_name_returns_existing_profile(app_use_test_db, db_session) -> None:
    """PR #236: повторное «Соня» (вторая запись, повтор после «время заняли») — тот же профиль, не дубль."""
    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                "/api/webapp/client/profiles", json={"first_name": "Соня"}, headers=_client_auth_headers()
            )
            again = await client.post(
                "/api/webapp/client/profiles", json={"first_name": "  соня "}, headers=_client_auth_headers()
            )
            other = await client.post(
                "/api/webapp/client/profiles", json={"first_name": "Маша"}, headers=_client_auth_headers()
            )
            same_with_surname = await client.post(
                "/api/webapp/client/profiles",
                json={"first_name": "Соня", "last_name": "Иванова"},
                headers=_client_auth_headers(),
            )
            r_list = await client.get("/api/webapp/client/profiles", headers=_client_auth_headers())

    assert first.status_code == again.status_code == other.status_code == 200
    sonya = first.json()["client_id"]
    assert again.json()["client_id"] == sonya
    # «Соня» без фамилии и «Соня Иванова» — разные дети (L1): не склеиваем.
    assert same_with_surname.json()["client_id"] not in (sonya, parent_id)
    assert other.json()["client_id"] not in (sonya, parent_id)
    ids = sorted(p["client_id"] for p in r_list.json()["items"])
    assert ids == sorted([parent_id, sonya, other.json()["client_id"], same_with_surname.json()["client_id"]])


@pytest.mark.asyncio
async def test_post_profiles_surname_must_match_or_be_absent_on_both(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    async def post(client, **body):
        r = await client.post("/api/webapp/client/profiles", json=body, headers=_client_auth_headers())
        assert r.status_code == 200, r.text
        return r.json()["client_id"]

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            full = await post(client, first_name="Саша", last_name="Иванова")
            again = await post(client, first_name=" саша ", last_name="  иванова")
            bare = await post(client, first_name="Саша")  # у существующей есть фамилия, у нового нет
    assert again == full
    assert bare != full


@pytest.mark.asyncio
async def test_post_profiles_same_name_different_surname_is_another_child(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            a = await client.post(
                "/api/webapp/client/profiles",
                json={"first_name": "Ваня", "last_name": "Петров"},
                headers=_client_auth_headers(),
            )
            b = await client.post(
                "/api/webapp/client/profiles",
                json={"first_name": "Ваня", "last_name": "Сидоров"},
                headers=_client_auth_headers(),
            )
    assert a.json()["client_id"] != b.json()["client_id"]


@pytest.mark.asyncio
async def test_post_profiles_does_not_reuse_another_accounts_child(app_use_test_db, db_session) -> None:
    tid_a = _fresh_client_telegram_id()
    tid_b = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid_a, first_name="Мама А")
    await _insert_client(db_session, telegram_id=tid_b, first_name="Мама Б")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_init_auth(tid_a):
            a = await client.post("/api/webapp/client/profiles", json={"first_name": "Соня"}, headers=_client_auth_headers())
        with patch_client_init_auth(tid_b):
            b = await client.post("/api/webapp/client/profiles", json={"first_name": "Соня"}, headers=_client_auth_headers())
    assert a.json()["client_id"] != b.json()["client_id"]
