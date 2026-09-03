"""
TASK-007: GET /api/webapp/client/bookings/history — auth, happy path, trainer_id filter.
GET /api/webapp/client/bookings also gains trainer_options in its response body.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app

from tests.api.test_webapp_client_miniapp_integration import patch_client_init_auth
from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service
from tests.conftest import belarus_test_phone


def _fresh_client_telegram_id() -> int:
    return 7_500_000_000 + (uuid.uuid4().int % 500_000_000)


async def _seed_client(db_session, tg: int) -> int:
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    return int(client_id)


async def _seed_past_booking(db_session, *, trainer_id: int, client_id: int, service_id: int, status: str) -> int:
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date - 1,
                TIME '10:00', TIME '11:00', 'booked'
            )
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (slot_id,) = r_slot.fetchone()
    r_booking = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, :status) RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id, "status": status},
    )
    (booking_id,) = r_booking.fetchone()
    return int(booking_id)


@pytest.mark.asyncio
async def test_history_route_requires_auth(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/client/bookings/history")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_history_route_happy_path(app_use_test_db, db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tg = _fresh_client_telegram_id()
    client_id = await _seed_client(db_session, tg)
    booking_id = await _seed_past_booking(db_session, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="completed")
    await db_session.commit()

    with patch_client_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/client/bookings/history",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    body = resp.json()
    days = body.get("days") or []
    ids = [b["id"] for d in days for b in d.get("bookings") or []]
    assert booking_id in ids
    assert "has_more" in body


@pytest.mark.asyncio
async def test_history_route_trainer_id_filter_narrows_results(app_use_test_db, db_session) -> None:
    trainer_a, service_a = await _seed_trainer_with_service(db_session)
    trainer_b, service_b = await _seed_trainer_with_service(db_session)
    tg = _fresh_client_telegram_id()
    client_id = await _seed_client(db_session, tg)
    id_a = await _seed_past_booking(db_session, trainer_id=trainer_a, client_id=client_id, service_id=service_a, status="completed")
    id_b = await _seed_past_booking(db_session, trainer_id=trainer_b, client_id=client_id, service_id=service_b, status="completed")
    await db_session.commit()

    with patch_client_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/client/bookings/history?trainer_id={trainer_a}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    ids = [b["id"] for d in resp.json().get("days") or [] for b in d.get("bookings") or []]
    assert id_a in ids
    assert id_b not in ids


@pytest.mark.asyncio
async def test_upcoming_route_includes_trainer_options(app_use_test_db, db_session) -> None:
    trainer_a, service_a = await _seed_trainer_with_service(db_session)
    trainer_b, service_b = await _seed_trainer_with_service(db_session)
    tg = _fresh_client_telegram_id()
    client_id = await _seed_client(db_session, tg)
    await _seed_past_booking(db_session, trainer_id=trainer_a, client_id=client_id, service_id=service_a, status="completed")
    await _seed_past_booking(db_session, trainer_id=trainer_b, client_id=client_id, service_id=service_b, status="completed")
    await db_session.commit()

    with patch_client_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/client/bookings",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    options = resp.json().get("trainer_options") or []
    assert {o["trainer_id"] for o in options} == {trainer_a, trainer_b}
