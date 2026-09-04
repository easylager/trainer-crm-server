"""
Booking attribution for multi-profile accounts: X-Profile-Id must land bookings on the
selected guardian/child client_id (not the parent's self row), including when that child
is also the account default.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.test_webapp_client_miniapp_integration import (
    _client_auth_headers,
    _create_trainer_online_with_slot,
    patch_client_init_auth,
)
from tests.conftest import belarus_test_phone


def _fresh_client_telegram_id() -> int:
    return 7_810_000_000 + (uuid.uuid4().int % 2_000_000_000)


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
    return int(r.json()["client_id"])


async def _set_default_profile(client, *, profile_client_id: int) -> None:
    r = await client.patch(
        f"/api/webapp/client/profiles/{profile_client_id}/default",
        headers=_client_auth_headers(),
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_booking_with_x_profile_id_attributes_to_guardian_child(
    app_use_test_db, db_session
) -> None:
    """POST /client/booking with X-Profile-Id=<child> stores bookings.client_id = child."""
    slot_day = date.today() + timedelta(days=14)
    ref_day = slot_day - timedelta(days=slot_day.weekday())
    ref_now = datetime.combine(ref_day, time(10, 0))
    _trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )

    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")
    phone, _norm = belarus_test_phone(tid)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Лера")
            await _set_default_profile(client, profile_client_id=child_id)

            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                book = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                    },
                    headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
                )

    assert book.status_code == 200, book.text
    booking_id = book.json()["booking_id"]

    r = await db_session.execute(
        text("SELECT client_id FROM bookings WHERE id = :bid"), {"bid": booking_id}
    )
    booked_for = int(r.scalar_one())
    assert booked_for == child_id
    assert booked_for != parent_id


@pytest.mark.asyncio
async def test_booking_with_header_when_child_is_default_still_lands_on_child(
    app_use_test_db, db_session
) -> None:
    """
    Regression for Task 1: when the child is both active and default, the client now always
    sends X-Profile-Id. Server must still attribute the booking to the child (not self).
    """
    slot_day = date.today() + timedelta(days=16)
    ref_day = slot_day - timedelta(days=slot_day.weekday())
    ref_now = datetime.combine(ref_day, time(10, 0))
    _trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={19}
    )

    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Папа")
    phone, _norm = belarus_test_phone(tid)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Ваня")
            await _set_default_profile(client, profile_client_id=child_id)

            # Explicit header even though child is default — mirrors the fixed fetch patch.
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                book = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                    },
                    headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
                )

    assert book.status_code == 200, book.text
    booking_id = book.json()["booking_id"]

    r = await db_session.execute(
        text("SELECT client_id FROM bookings WHERE id = :bid"), {"bid": booking_id}
    )
    booked_for = int(r.scalar_one())
    assert booked_for == child_id
    assert booked_for != parent_id
