"""TASK-056: client self-booking place = slot arena; mismatch flag before confirm."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ONLINE
from tests.api.test_webapp_client_miniapp_integration import (
    _ensure_trainer_subscription_tier,
    patch_client_init_auth,
)
from tests.conftest import belarus_test_phone
from tests.db_catalog_helpers import require_seed_service_id


def _fresh_tg() -> int:
    return 7_100_000_000 + (uuid.uuid4().int % 2_000_000_000)


async def _two_arenas(session) -> tuple[int, int, int]:
    r = await session.execute(
        text(
            """
            SELECT id, city_id FROM arenas
            WHERE COALESCE(is_active, true)
            ORDER BY id
            LIMIT 2
            """
        )
    )
    rows = r.fetchall()
    if len(rows) < 2:
        pytest.skip("Need at least two seeded arenas")
    return int(rows[0][0]), int(rows[1][0]), int(rows[0][1])


async def _seed_online_trainer_two_arenas(session, *, primary: int, secondary: int, city_id: int):
    service_id = await require_seed_service_id(session)
    r = await session.execute(
        text("INSERT INTO trainers (status, primary_arena_id, is_catalog_visible) VALUES ('active', :a, true) RETURNING id"),
        {"a": primary},
    )
    trainer_id = int(r.scalar_one())
    await session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id, min_hours_before_booking)
            VALUES (:tid, 'Ice', 'Place', 32, :cid, 0)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    for aid in (primary, secondary):
        await session.execute(
            text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
            {"tid": trainer_id, "aid": aid},
        )
    await session.commit()
    await _ensure_trainer_subscription_tier(session, trainer_id, SUBSCRIPTION_TIER_ONLINE)
    return trainer_id, service_id


async def _insert_available_slot(session, trainer_id: int, slot_date: date, *, arena_id: int | None, hour: int = 18) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, :st, :et, 'available', :aid)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": slot_date,
            "st": time(hour, 0),
            "et": time(hour + 1, 0),
            "aid": arena_id,
        },
    )
    slot_id = int(r.scalar_one())
    await session.commit()
    return slot_id


def _monday_ref() -> tuple[date, datetime]:
    d = date(2026, 3, 9)
    return d, datetime(2026, 3, 9, 10, 0, 0)


@pytest.mark.asyncio
async def test_post_booking_uses_slot_arena_not_primary(app_use_test_db, db_session) -> None:
    """AC-001: client came from X, books slot on X → bookings.arena_id = X (primary is Y)."""
    primary, secondary, city_id = await _two_arenas(db_session)
    trainer_id, service_id = await _seed_online_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )
    ref_day, ref_now = _monday_ref()
    slot_day = ref_day + timedelta(days=3)
    slot_id = await _insert_available_slot(db_session, trainer_id, slot_day, arena_id=secondary)
    ctg = _fresh_tg()
    phone, _ = belarus_test_phone(ctg)
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state, city_id, selected_service_id, selected_arena_id, selected_trainer_id)
            VALUES (:tg, 'idle', :cid, :sid, :aid, :tid)
            """
        ),
        {"tg": ctg, "cid": city_id, "sid": service_id, "aid": secondary, "tid": trainer_id},
    )
    await db_session.commit()

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.get_slots_cached", return_value=None):
                book = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                        "first_name": "Клиент",
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert book.status_code == 200, book.text
    data = book.json()
    assert data.get("success") is True
    assert data.get("place_mismatch") is not True
    bid = int(data["booking_id"])
    row = await db_session.execute(text("SELECT arena_id FROM bookings WHERE id = :bid"), {"bid": bid})
    assert int(row.scalar_one()) == secondary


@pytest.mark.asyncio
async def test_post_booking_place_mismatch_flag_when_origin_differs(app_use_test_db, db_session) -> None:
    """AC-002: booked place is slot arena; API flags mismatch vs catalog origin arena."""
    primary, secondary, city_id = await _two_arenas(db_session)
    trainer_id, service_id = await _seed_online_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )
    ref_day, _ = _monday_ref()
    slot_day = ref_day + timedelta(days=4)
    slot_id = await _insert_available_slot(db_session, trainer_id, slot_day, arena_id=primary)
    ctg = _fresh_tg()
    phone, _ = belarus_test_phone(ctg)
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state, selected_arena_id)
            VALUES (:tg, 'idle', :aid)
            """
        ),
        {"tg": ctg, "aid": secondary},
    )
    await db_session.commit()

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            book = await client.post(
                "/api/webapp/client/booking",
                json={
                    "slot_id": slot_id,
                    "phone": phone,
                    "service_id": service_id,
                    "first_name": "Клиент",
                },
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert book.status_code == 200, book.text
    data = book.json()
    assert data.get("place_mismatch") is True
    bid = int(data["booking_id"])
    row = await db_session.execute(text("SELECT arena_id FROM bookings WHERE id = :bid"), {"bid": bid})
    assert int(row.scalar_one()) == primary


@pytest.mark.asyncio
async def test_get_client_slots_null_arena_resolves_to_schedule_default(app_use_test_db, db_session) -> None:
    """TASK-056 note: GET /client/slots already fills NULL slot arena with schedule default — do not regress."""
    primary, secondary, city_id = await _two_arenas(db_session)
    trainer_id, _sid = await _seed_online_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )
    ref_day, ref_now = _monday_ref()
    slot_day = ref_day + timedelta(days=2)
    await _insert_available_slot(db_session, trainer_id, slot_day, arena_id=None, hour=16)
    ctg = _fresh_tg()

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("src.api.routes.webapp.get_slots_cached", return_value=None),
                patch("src.api.routes.webapp.datetime") as mock_dt,
                patch("src.api.routes.webapp.date") as mock_date,
            ):
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                resp = await client.get(
                    f"/api/webapp/client/slots?trainer_id={trainer_id}&min_hours=0",
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 200, resp.text
    slots = resp.json().get("slots") or []
    assert slots, "NULL-arena slot must still be listed"
    assert int(slots[0]["arena_id"]) == primary


@pytest.mark.asyncio
async def test_get_client_slots_place_mismatch_vs_session_origin(app_use_test_db, db_session) -> None:
    """AC-002: slot payload exposes place_mismatch when origin arena ≠ slot place."""
    primary, secondary, city_id = await _two_arenas(db_session)
    trainer_id, _sid = await _seed_online_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )
    ref_day, ref_now = _monday_ref()
    slot_day = ref_day + timedelta(days=2)
    await _insert_available_slot(db_session, trainer_id, slot_day, arena_id=primary, hour=17)
    ctg = _fresh_tg()
    await db_session.execute(
        text("INSERT INTO client_sessions (telegram_id, state, selected_arena_id) VALUES (:tg, 'idle', :aid)"),
        {"tg": ctg, "aid": secondary},
    )
    await db_session.commit()

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("src.api.routes.webapp.get_slots_cached", return_value=None),
                patch("src.api.routes.webapp.datetime") as mock_dt,
                patch("src.api.routes.webapp.date") as mock_date,
            ):
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                resp = await client.get(
                    f"/api/webapp/client/slots?trainer_id={trainer_id}&min_hours=0",
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 200, resp.text
    slots = resp.json().get("slots") or []
    assert slots
    assert slots[0].get("place_mismatch") is True
    assert int(slots[0]["arena_id"]) == primary


@pytest.mark.asyncio
async def test_get_client_slots_empty_filter_explains_other_venues(app_use_test_db, db_session) -> None:
    """In-scope: arena X filter with zero slots on X is not a silent dead end."""
    primary, secondary, city_id = await _two_arenas(db_session)
    trainer_id, _sid = await _seed_online_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )
    ref_day, ref_now = _monday_ref()
    slot_day = ref_day + timedelta(days=2)
    await _insert_available_slot(db_session, trainer_id, slot_day, arena_id=primary, hour=15)
    ctg = _fresh_tg()

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("src.api.routes.webapp.get_slots_cached", return_value=None),
                patch("src.api.routes.webapp.datetime") as mock_dt,
                patch("src.api.routes.webapp.date") as mock_date,
            ):
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                resp = await client.get(
                    f"/api/webapp/client/slots?trainer_id={trainer_id}&min_hours=0&arena_ids={secondary}",
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("slots") == []
    assert body.get("empty_on_filter") is True
    hint = (body.get("empty_on_filter_hint") or "")
    assert "заявк" in hint.lower() or "площад" in hint.lower()
