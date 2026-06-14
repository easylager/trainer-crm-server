"""API tests for studio_central center sessions (ADR-003 W2)."""
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.collective_api_helpers import seed_active_collective_member, seed_active_collective_owner
from tests.api.test_webapp_client_miniapp_integration import patch_client_init_auth
from tests.api.test_webapp_trainer_schedule_integration import (
    _create_active_trainer,
    _fresh_trainer_telegram_id,
    patch_trainer_webapp_init,
)

pytestmark = pytest.mark.collective


@pytest.mark.asyncio
async def test_trainer_create_and_list_center_sessions(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await seed_active_collective_owner(
        db_session,
        trainer_id,
        slug="center-grid",
        schedule_mode="studio_central",
    )
    slot_date = (date.today() + timedelta(days=5)).isoformat()
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create = await client.post(
                "/api/webapp/trainer/collective/sessions",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": slot_date,
                    "start_time": "14:00",
                    "end_time": "15:00",
                    "capacity": 3,
                },
            )
            assert create.status_code == 200, create.text
            body = create.json()
            assert body["capacity"] == 3
            assert body["start_time"] == "14:00"

            listed = await client.get(
                "/api/webapp/trainer/collective/sessions",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert listed.status_code == 200
            sessions = listed.json()["sessions"]
            assert any(s["id"] == body["id"] for s in sessions)


@pytest.mark.asyncio
async def test_public_collective_sessions(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await seed_active_collective_owner(
        db_session,
        trainer_id,
        slug="public-center",
        schedule_mode="studio_central",
    )
    slot_date = date.today() + timedelta(days=2)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/webapp/trainer/collective/sessions",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": slot_date.isoformat(),
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "capacity": 1,
                },
            )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/collectives/public-center/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["schedule_mode"] == "studio_central"
    assert len(data["sessions"]) >= 1
    assert data["tariffs"]["lane_hour_cents"] == 2000


@pytest.mark.asyncio
async def test_client_collective_session_booking(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await seed_active_collective_owner(
        db_session,
        trainer_id,
        slug="client-book",
        schedule_mode="studio_central",
    )
    slot_date = date.today() + timedelta(days=1)
    session_id: int
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/webapp/trainer/collective/sessions",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": slot_date.isoformat(),
                    "start_time": "16:00",
                    "end_time": "17:00",
                    "capacity": 1,
                },
            )
            session_id = int(created.json()["id"])

    ctg = _fresh_trainer_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/client/collective-session-booking",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "session_id": session_id,
                    "attendance_mode": "lane_self",
                    "phone": "+375291234567",
                    "first_name": "Test",
                },
            )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["booking_price_cents"] == 2000

    r = await db_session.execute(
        text("SELECT status FROM collective_session_bookings WHERE id = :id"),
        {"id": body["booking_id"]},
    )
    assert str(r.scalar_one()) == "pending"


@pytest.mark.asyncio
async def test_client_collective_session_booking_with_coach(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    cid = await seed_active_collective_owner(
        db_session,
        trainer_id,
        slug="client-coach-mode",
        schedule_mode="studio_central",
    )
    member_id = await seed_active_collective_member(db_session, cid)
    slot_date = date.today() + timedelta(days=1)
    session_id: int
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/webapp/trainer/collective/sessions",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": slot_date.isoformat(),
                    "start_time": "11:00",
                    "end_time": "12:00",
                    "capacity": 2,
                    "coach_trainer_ids": [member_id],
                },
            )
            session_id = int(created.json()["id"])

    ctg = _fresh_trainer_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/client/collective-session-booking",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "session_id": session_id,
                    "attendance_mode": "center_coach_individual",
                    "center_coach_id": member_id,
                    "phone": "+375291234567",
                    "first_name": "Coach",
                },
            )
    assert resp.status_code == 200, resp.text
    assert resp.json()["booking_price_cents"] == 7000
