"""Which concrete pass instance covers one booking, for the booking detail card (TASK-040)."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_payment_notice import resolve_pass_instance_for_booking
from src.application.booking_use_cases import create_booking
from src.application.pass_product_use_cases import (
    issue_pass_to_client,
    redeem_pass_session_for_booking,
)
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


async def _seed_trainer_client_pass(
    session: AsyncSession,
    *,
    sessions_total: int,
) -> tuple[int, int, int, int]:
    service_id = await require_seed_service_id(session)
    r = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Pass', 'Trainer', 30)"
        ),
        {"tid": trainer_id},
    )
    await session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) "
            "VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    tg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(tg)
    r = await session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tid, 'Pass', 'Client', :phone, :phone_normalized)
            RETURNING id
            """
        ),
        {"tid": tg, "phone": phone, "phone_normalized": phone_normalized},
    )
    (client_id,) = r.fetchone()
    r = await session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active)
            VALUES (:tid, '5 visits', :total, 20000, TRUE)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "total": sessions_total},
    )
    (pass_product_id,) = r.fetchone()
    await session.execute(
        text("INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:tid, :cid)"),
        {"tid": trainer_id, "cid": client_id},
    )
    await session.commit()
    issued = await issue_pass_to_client(session, trainer_id, client_id, pass_product_id)
    assert issued is not None
    return trainer_id, client_id, service_id, pass_product_id


async def _create_slot(
    session: AsyncSession,
    *,
    trainer_id: int,
    slot_date: date,
    start: time,
    end: time,
) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, :start, :end, 'available', 1)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date, "start": start, "end": end},
    )
    (slot_id,) = r.fetchone()
    await session.commit()
    return int(slot_id)


@pytest.mark.asyncio
async def test_resolves_the_actually_redeemed_instance_for_a_past_visit(
    db_session: AsyncSession,
) -> None:
    trainer_id, client_id, service_id, pass_product_id = await _seed_trainer_client_pass(
        db_session, sessions_total=5
    )
    slot_id = await _create_slot(
        db_session,
        trainer_id=trainer_id,
        slot_date=date.today() - timedelta(days=1),
        start=time(10, 0),
        end=time(11, 0),
    )
    booking_id, _ = await create_booking(
        db_session, slot_id, trainer_id, client_id, service_id=service_id, created_by_trainer=True
    )
    assert booking_id is not None
    await db_session.execute(
        text("UPDATE bookings SET status = 'completed' WHERE id = :bid"), {"bid": booking_id}
    )
    await db_session.commit()
    assert await redeem_pass_session_for_booking(db_session, booking_id) is True

    result = await resolve_pass_instance_for_booking(db_session, booking_id, client_id, trainer_id)
    assert result is not None
    assert result["sessions_total"] == 5
    assert result["sessions_remaining"] == 4
    assert result["product_name"] == "5 visits"


@pytest.mark.asyncio
async def test_resolves_the_projected_instance_for_an_unredeemed_future_visit(
    db_session: AsyncSession,
) -> None:
    trainer_id, client_id, service_id, pass_product_id = await _seed_trainer_client_pass(
        db_session, sessions_total=2
    )
    slot_id = await _create_slot(
        db_session,
        trainer_id=trainer_id,
        slot_date=date.today() + timedelta(days=2),
        start=time(10, 0),
        end=time(11, 0),
    )
    booking_id, _ = await create_booking(
        db_session, slot_id, trainer_id, client_id, service_id=service_id, created_by_trainer=True
    )
    assert booking_id is not None

    result = await resolve_pass_instance_for_booking(db_session, booking_id, client_id, trainer_id)
    assert result is not None
    assert result["sessions_total"] == 2
    assert result["sessions_remaining"] == 2


@pytest.mark.asyncio
async def test_returns_none_when_queue_has_no_pass_left_for_this_visit(
    db_session: AsyncSession,
) -> None:
    trainer_id, client_id, service_id, _ = await _seed_trainer_client_pass(
        db_session, sessions_total=1
    )
    base = date.today() + timedelta(days=3)
    booking_ids: list[int] = []
    for offset in range(2):
        slot_id = await _create_slot(
            db_session,
            trainer_id=trainer_id,
            slot_date=base + timedelta(days=offset),
            start=time(9, 0),
            end=time(10, 0),
        )
        booking_id, _ = await create_booking(
            db_session, slot_id, trainer_id, client_id, service_id=service_id, created_by_trainer=True
        )
        assert booking_id is not None
        booking_ids.append(int(booking_id))

    first = await resolve_pass_instance_for_booking(
        db_session, booking_ids[0], client_id, trainer_id
    )
    assert first is not None

    second = await resolve_pass_instance_for_booking(
        db_session, booking_ids[1], client_id, trainer_id
    )
    assert second is None
