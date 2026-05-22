"""Pass issue must not require a live (non-cancelled) booking."""
from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.pass_product_use_cases import issue_pass_to_client
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


async def _trainer_with_pass_product(db_session) -> tuple[int, int]:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active, sort_order)
            VALUES (:tid, 'Ab5', 5, 50_000, true, 0)
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (product_id,) = r.fetchone()
    await db_session.commit()
    return trainer_id, product_id


async def _insert_client(db_session) -> int:
    tg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, phone, phone_normalized, first_name)
            VALUES (:tg, :phone, :phone_normalized, 'Pass')
            RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "phone_normalized": phone_normalized},
    )
    (client_id,) = r.fetchone()
    await db_session.commit()
    return client_id


@pytest.mark.asyncio
async def test_issue_pass_roster_only_without_bookings(db_session) -> None:
    trainer_id, product_id = await _trainer_with_pass_product(db_session)
    client_id = await _insert_client(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:tid, :cid)"
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    await db_session.commit()

    result = await issue_pass_to_client(db_session, trainer_id, client_id, product_id)

    assert result["client_id"] == client_id
    assert result["sessions_total"] == 5
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_issue_pass_when_only_cancelled_bookings(db_session) -> None:
    service_id = await require_seed_service_id(db_session)
    trainer_id, product_id = await _trainer_with_pass_product(db_session)
    client_id = await _insert_client(db_session)
    slot_date = date.today() + timedelta(days=3)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date, "st": time(10, 0), "et": time(11, 0)},
    )
    (slot_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'cancelled')
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    result = await issue_pass_to_client(db_session, trainer_id, client_id, product_id)

    assert result["client_id"] == client_id
    assert result["pass_product_id"] == product_id
