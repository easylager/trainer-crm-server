"""Chronological pass/cert allocation for upcoming booking payment display."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_payment_notice import resolve_bookings_expected_payment_class_map
from src.application.booking_use_cases import cancel_booking, create_booking
from src.application.pass_product_use_cases import issue_pass_to_client
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
        text(
            "INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:tid, :cid)"
        ),
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
async def test_only_first_n_upcoming_bookings_get_pass_when_sessions_limited(
    db_session: AsyncSession,
) -> None:
    trainer_id, client_id, service_id, _ = await _seed_trainer_client_pass(
        db_session, sessions_total=3
    )
    base = date.today() + timedelta(days=2)
    booking_ids: list[int] = []
    for offset in range(4):
        slot_id = await _create_slot(
            db_session,
            trainer_id=trainer_id,
            slot_date=base + timedelta(days=offset),
            start=time(10, 0),
            end=time(11, 0),
        )
        booking_id, _ = await create_booking(
            db_session,
            slot_id,
            trainer_id,
            client_id,
            service_id=service_id,
            created_by_trainer=True,
        )
        assert booking_id is not None
        booking_ids.append(int(booking_id))

    pc_map = await resolve_bookings_expected_payment_class_map(
        db_session,
        [(bid, trainer_id) for bid in booking_ids],
    )
    assert [pc_map[bid] for bid in booking_ids] == ["PASS", "PASS", "PASS", "ONE_OFF"]


@pytest.mark.asyncio
async def test_cancel_earlier_visit_promotes_later_to_pass(db_session: AsyncSession) -> None:
    """Freeing an earlier slot in the queue lets a later visit inherit pass coverage."""
    trainer_id, client_id, service_id, _ = await _seed_trainer_client_pass(
        db_session, sessions_total=3
    )
    base = date.today() + timedelta(days=3)
    booking_ids: list[int] = []
    for offset in range(4):
        slot_id = await _create_slot(
            db_session,
            trainer_id=trainer_id,
            slot_date=base + timedelta(days=offset),
            start=time(11, 0),
            end=time(12, 0),
        )
        booking_id, _ = await create_booking(
            db_session,
            slot_id,
            trainer_id,
            client_id,
            service_id=service_id,
            created_by_trainer=True,
        )
        assert booking_id is not None
        booking_ids.append(int(booking_id))

    before = await resolve_bookings_expected_payment_class_map(
        db_session, [(bid, trainer_id) for bid in booking_ids]
    )
    assert before[booking_ids[3]] == "ONE_OFF"

    assert await cancel_booking(
        db_session, booking_ids[0], trainer_id, notify_client=False
    )

    after = await resolve_bookings_expected_payment_class_map(
        db_session, [(bid, trainer_id) for bid in booking_ids]
    )
    assert after[booking_ids[0]] is None
    assert after[booking_ids[1]] == "PASS"
    assert after[booking_ids[2]] == "PASS"
    assert after[booking_ids[3]] == "PASS"


@pytest.mark.asyncio
async def test_cancel_middle_visit_rebalances_remaining_queue(db_session: AsyncSession) -> None:
    trainer_id, client_id, service_id, _ = await _seed_trainer_client_pass(
        db_session, sessions_total=3
    )
    base = date.today() + timedelta(days=4)
    booking_ids: list[int] = []
    for offset in range(4):
        slot_id = await _create_slot(
            db_session,
            trainer_id=trainer_id,
            slot_date=base + timedelta(days=offset),
            start=time(9, 0),
            end=time(10, 0),
        )
        booking_id, _ = await create_booking(
            db_session,
            slot_id,
            trainer_id,
            client_id,
            service_id=service_id,
            created_by_trainer=True,
        )
        assert booking_id is not None
        booking_ids.append(int(booking_id))

    assert await cancel_booking(
        db_session, booking_ids[1], trainer_id, notify_client=False
    )

    pc_map = await resolve_bookings_expected_payment_class_map(
        db_session, [(bid, trainer_id) for bid in booking_ids]
    )
    assert pc_map[booking_ids[0]] == "PASS"
    assert pc_map[booking_ids[1]] is None
    assert pc_map[booking_ids[2]] == "PASS"
    assert pc_map[booking_ids[3]] == "PASS"
