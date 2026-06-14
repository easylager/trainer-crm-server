"""Wave B: hub inbox-count, bootstrap action_inbox, confirm-batch."""
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.test_webapp_trainer_schedule_integration import (
    _create_active_trainer,
    _fresh_trainer_telegram_id,
    patch_trainer_webapp_init,
)
from tests.db_catalog_helpers import require_seed_service_id


async def _insert_pending_booking(db_session, trainer_id: int) -> int:
    service_id = await require_seed_service_id(db_session)
    slot_date = date.today() + timedelta(days=2)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :sd, '10:00', '11:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "sd": slot_date},
    )
    slot_id = int(r_slot.scalar_one())
    tg = 8_000_000_000 + (uuid.uuid4().int % 1_000_000_000)
    r_client = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone)
            VALUES (:tg, 'Inbox', 'Client', '+375291234567')
            RETURNING id
            """
        ),
        {"tg": tg},
    )
    client_id = int(r_client.scalar_one())
    r_book = await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
            VALUES (:tid, :cid, :sid, :svc, 'pending')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
    )
    booking_id = int(r_book.scalar_one())
    await db_session.commit()
    return booking_id


@pytest.mark.asyncio
async def test_hub_inbox_count_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/trainer/hub/inbox-count")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_hub_inbox_count_returns_badges(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/hub/inbox-count",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "badges" in data
    assert set(data["badges"].keys()) == {"schedule", "more", "clients"}
    assert isinstance(data["total_actionable"], int)


@pytest.mark.asyncio
async def test_hub_bootstrap_includes_action_inbox(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/hub/bootstrap?bookings_limit=10",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "action_inbox" in data
    assert data["action_inbox"] is not None
    assert "items" in data["action_inbox"]
    assert "badges" in data["action_inbox"]


@pytest.mark.asyncio
async def test_hub_inbox_event_records_audit(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/hub/inbox-event",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "event": "inbox_item_shown",
                    "surface": "hub",
                    "item_id": "pending_bookings",
                    "kind": "pending",
                    "count": 2,
                },
            )
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


@pytest.mark.asyncio
async def test_confirm_batch_confirms_pending(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    bid = await _insert_pending_booking(db_session, trainer_id)
    with patch_trainer_webapp_init(tg), patch(
        "src.api.routes.webapp.notify_client_booking_confirmed_by_trainer",
        new=AsyncMock(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/bookings/confirm-batch",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"booking_ids": [bid]},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed_count"] == 1
    assert bid in body["confirmed"]
    r = await db_session.execute(text("SELECT status FROM bookings WHERE id = :id"), {"id": bid})
    assert r.scalar_one() == "confirmed"
