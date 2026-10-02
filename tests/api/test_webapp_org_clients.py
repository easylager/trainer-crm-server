"""TASK-141 (S7): GET /api/webapp/org/clients — aggregated client list.

Tests cover:
- Empty client list for fresh school
- Clients aggregated across multiple trainers in the collective
- 401 without initData
- 404 for non-operator
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.collective_use_cases import (
    consume_collective_claim_token_for_operator,
    create_collective_draft,
    issue_collective_claim_token,
)

pytestmark = pytest.mark.collective


@contextmanager
def patch_org_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


async def _claim_school(db_session, *, slug: str, telegram_id: int) -> int:
    created = await create_collective_draft(db_session, slug=slug, display_name=slug)
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    outcome = await consume_collective_claim_token_for_operator(db_session, claim["token"], telegram_id)
    assert outcome.error is None
    return int(created["id"])


async def _create_trainer(db_session, telegram_id: int) -> int:
    r = await db_session.execute(
        text(
            "INSERT INTO trainers (status, telegram_id, studio_access_mode, created_at) "
            "VALUES ('active', :tgid, 'full_trainer', :now) RETURNING id"
        ),
        {"tgid": telegram_id, "now": datetime.now(timezone.utc)},
    )
    return int(r.scalar_one())


async def _add_trainer_to_collective(db_session, collective_id: int, trainer_id: int) -> None:
    await db_session.execute(
        text(
            "INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at) "
            "VALUES (:cid, :tid, 'member', 'active', now())"
        ),
        {"cid": collective_id, "tid": trainer_id},
    )
    await db_session.commit()


async def _create_client(db_session, *, first_name: str = "Test", last_name: str = "Client", phone: str | None = None) -> int:
    r = await db_session.execute(
        text(
            "INSERT INTO clients (first_name, last_name, phone, created_at, updated_at) "
            "VALUES (:fn, :ln, :phone, now(), now()) RETURNING id"
        ),
        {"fn": first_name, "ln": last_name, "phone": phone},
    )
    return int(r.scalar_one())


async def _create_booking(db_session, trainer_id: int, client_id: int) -> None:
    """Create a minimal booking to link client to trainer."""
    # First create a slot
    r = await db_session.execute(
        text(
            "INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity) "
            "VALUES (:tid, CURRENT_DATE, '10:00', '11:00', 'available', 1) RETURNING id"
        ),
        {"tid": trainer_id},
    )
    slot_id = int(r.scalar_one())

    # Get or create a service for this trainer
    r = await db_session.execute(
        text(
            "SELECT s.id FROM services s "
            "JOIN trainer_services ts ON ts.service_id = s.id "
            "WHERE ts.trainer_id = :tid LIMIT 1"
        ),
        {"tid": trainer_id},
    )
    service_id = r.scalar()
    if service_id is None:
        r = await db_session.execute(
            text("INSERT INTO services (name, created_by_trainer_id) VALUES ('Test Service', :tid) RETURNING id"),
            {"tid": trainer_id},
        )
        service_id = int(r.scalar_one())
        await db_session.execute(
            text("INSERT INTO trainer_services (trainer_id, service_id) VALUES (:tid, :sid)"),
            {"tid": trainer_id, "sid": service_id},
        )

    await db_session.execute(
        text(
            "INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status, created_at) "
            "VALUES (:tid, :cid, :sid, :svc, 'confirmed', now())"
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_org_clients_empty_for_fresh_school(app_use_test_db, db_session) -> None:
    telegram_id = 8_700_000_001
    await _claim_school(db_session, slug="org-clients-empty", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/webapp/org/clients", headers={"X-Telegram-Init-Data": "mock"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["clients"] == []
    assert body["role"] == "owner"


@pytest.mark.asyncio
async def test_org_clients_aggregated_across_trainers(app_use_test_db, db_session) -> None:
    telegram_id = 8_700_000_002
    collective_id = await _claim_school(db_session, slug="org-clients-agg", telegram_id=telegram_id)

    trainer1_id = await _create_trainer(db_session, telegram_id + 1)
    trainer2_id = await _create_trainer(db_session, telegram_id + 2)
    await _add_trainer_to_collective(db_session, collective_id, trainer1_id)
    await _add_trainer_to_collective(db_session, collective_id, trainer2_id)

    client1_id = await _create_client(db_session, first_name="Alice", last_name="Smith", phone="+375291111111")
    client2_id = await _create_client(db_session, first_name="Bob", last_name="Jones", phone="+375292222222")

    await _create_booking(db_session, trainer1_id, client1_id)
    await _create_booking(db_session, trainer2_id, client2_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/webapp/org/clients", headers={"X-Telegram-Init-Data": "mock"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["clients"]) == 2
    client_ids = {c["client_id"] for c in body["clients"]}
    assert client1_id in client_ids
    assert client2_id in client_ids


@pytest.mark.asyncio
async def test_org_clients_deduplicated(app_use_test_db, db_session) -> None:
    """Same client booked with two trainers in the same collective appears once."""
    telegram_id = 8_700_000_003
    collective_id = await _claim_school(db_session, slug="org-clients-dedup", telegram_id=telegram_id)

    trainer1_id = await _create_trainer(db_session, telegram_id + 1)
    trainer2_id = await _create_trainer(db_session, telegram_id + 2)
    await _add_trainer_to_collective(db_session, collective_id, trainer1_id)
    await _add_trainer_to_collective(db_session, collective_id, trainer2_id)

    client_id = await _create_client(db_session, first_name="Shared", last_name="Client")

    await _create_booking(db_session, trainer1_id, client_id)
    await _create_booking(db_session, trainer2_id, client_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/webapp/org/clients", headers={"X-Telegram-Init-Data": "mock"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["clients"]) == 1
    assert body["clients"][0]["client_id"] == client_id


@pytest.mark.asyncio
async def test_org_clients_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/org/clients")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_org_clients_404_for_non_operator(app_use_test_db) -> None:
    telegram_id = 8_700_000_004
    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/webapp/org/clients", headers={"X-Telegram-Init-Data": "mock"})
    assert resp.status_code == 404
