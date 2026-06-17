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


@pytest.mark.asyncio
async def test_center_inbox_list_confirm_decline(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await seed_active_collective_owner(
        db_session,
        trainer_id,
        slug="center-inbox",
        schedule_mode="studio_central",
    )
    slot_date = date.today() + timedelta(days=3)
    session_id: int
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/webapp/trainer/collective/sessions",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": slot_date.isoformat(),
                    "start_time": "12:00",
                    "end_time": "13:00",
                    "capacity": 2,
                },
            )
            assert created.status_code == 200, created.text
            session_id = int(created.json()["id"])

    ctg = _fresh_trainer_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            booked = await client.post(
                "/api/webapp/client/collective-session-booking",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "session_id": session_id,
                    "attendance_mode": "lane_self",
                    "phone": "+375291112233",
                    "first_name": "Inbox",
                },
            )
    assert booked.status_code == 200, booked.text
    booking_id = int(booked.json()["booking_id"])

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            inbox = await client.get(
                "/api/webapp/trainer/collective/session-bookings",
                headers={"X-Telegram-Init-Data": "mock"},
                params={"status": "pending"},
            )
            assert inbox.status_code == 200, inbox.text
            body = inbox.json()
            assert body["count"] == 1
            assert body["bookings"][0]["booking_id"] == booking_id
            assert body["bookings"][0]["attendance_mode"] == "lane_self"

            confirmed = await client.post(
                f"/api/webapp/trainer/collective/session-bookings/{booking_id}/confirm",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert confirmed.status_code == 200, confirmed.text

    r = await db_session.execute(
        text("SELECT status, trainer_id FROM collective_session_bookings WHERE id = :id"),
        {"id": booking_id},
    )
    row = r.fetchone()
    assert str(row[0]) == "confirmed"
    assert int(row[1]) == trainer_id


@pytest.mark.asyncio
async def test_duplicate_week_and_assign_coaches(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    cid = await seed_active_collective_owner(
        db_session,
        trainer_id,
        slug="center-dup",
        schedule_mode="studio_central",
    )
    member_id = await seed_active_collective_member(db_session, cid)
    monday = date.today() - timedelta(days=date.today().weekday())
    slot_date = monday + timedelta(days=2)
    session_id: int
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/webapp/trainer/collective/sessions",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": slot_date.isoformat(),
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "capacity": 1,
                    "coach_trainer_ids": [member_id],
                },
            )
            assert created.status_code == 200, created.text
            session_id = int(created.json()["id"])
            assert any(c["trainer_id"] == member_id for c in created.json()["assigned_coaches"])

            dup = await client.post(
                "/api/webapp/trainer/collective/sessions/duplicate-week",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"source_week_start": monday.isoformat(), "weeks_ahead": 1},
            )
            assert dup.status_code == 200, dup.text
            assert int(dup.json().get("created_count") or 0) >= 1

            patched = await client.patch(
                f"/api/webapp/trainer/collective/sessions/{session_id}/coaches",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"coach_trainer_ids": [member_id, trainer_id]},
            )
            assert patched.status_code == 200, patched.text
            coach_ids = {c["trainer_id"] for c in patched.json()["assigned_coaches"]}
            assert member_id in coach_ids and trainer_id in coach_ids
