"""Trainer retroactive pass redemption for completed sessions without pass."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.pass_product_use_cases import (
    issue_pass_to_client,
    list_redeemable_bookings_for_pass_instance,
    manual_redeem_pass_for_booking,
)
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


async def _seed_completed_booking_without_pass(
    session: AsyncSession,
    *,
    slot_date: date,
) -> tuple[int, int, int, int]:
    service_id = await require_seed_service_id(session)
    r = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Retro', 'Trainer', 30)"
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
            VALUES (:tid, 'Retro', 'Client', :phone, :phone_normalized)
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
            VALUES (:tid, '10 visits', 10, 40000, TRUE)
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (pass_product_id,) = r.fetchone()
    await session.execute(
        text("INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:tid, :cid)"),
        {"tid": trainer_id, "cid": client_id},
    )
    r = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, :start, :end, 'booked', 1)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": slot_date,
            "start": time(10, 0),
            "end": time(11, 0),
        },
    )
    (slot_id,) = r.fetchone()
    r = await session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, booking_price_cents)
            VALUES (:sid, :tid, :cid, :svc, 'completed', 5000)
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await session.commit()
    return trainer_id, client_id, int(booking_id), pass_product_id


@pytest.mark.asyncio
async def test_list_redeemable_bookings_after_pass_issue(db_session: AsyncSession) -> None:
    yesterday = date.today() - timedelta(days=2)
    trainer_id, client_id, booking_id, pass_product_id = await _seed_completed_booking_without_pass(
        db_session, slot_date=yesterday
    )
    issued = await issue_pass_to_client(db_session, trainer_id, client_id, pass_product_id)
    pass_instance_id = int(issued["id"])

    result = await list_redeemable_bookings_for_pass_instance(
        db_session, trainer_id, pass_instance_id
    )
    assert "error" not in result
    ids = [int(x["booking_id"]) for x in result["items"]]
    assert booking_id in ids


@pytest.mark.asyncio
async def test_manual_redeem_updates_pass_and_stats_ledger(db_session: AsyncSession) -> None:
    yesterday = date.today() - timedelta(days=3)
    trainer_id, client_id, booking_id, pass_product_id = await _seed_completed_booking_without_pass(
        db_session, slot_date=yesterday
    )
    issued = await issue_pass_to_client(db_session, trainer_id, client_id, pass_product_id)
    pass_instance_id = int(issued["id"])
    assert issued["sessions_remaining"] == 10

    out = await manual_redeem_pass_for_booking(
        db_session, trainer_id, pass_instance_id, booking_id
    )
    assert out["already_redeemed"] is False
    assert out["pass"]["sessions_remaining"] == 9

    r = await db_session.execute(
        text(
            """
            SELECT pass_instance_id FROM pass_redemptions WHERE booking_id = :bid
            """
        ),
        {"bid": booking_id},
    )
    row = r.fetchone()
    assert row is not None
    assert int(row[0]) == pass_instance_id

    again = await list_redeemable_bookings_for_pass_instance(
        db_session, trainer_id, pass_instance_id
    )
    assert booking_id not in [int(x["booking_id"]) for x in again["items"]]

    dup = await manual_redeem_pass_for_booking(
        db_session, trainer_id, pass_instance_id, booking_id
    )
    assert dup["already_redeemed"] is True
    assert dup["pass"]["sessions_remaining"] == 9


@pytest.mark.asyncio
async def test_manual_redeem_completes_past_confirmed_booking(db_session: AsyncSession) -> None:
    """Past confirmed booking (not yet auto-completed) must appear and redeemable in one step."""
    yesterday = date.today() - timedelta(days=2)
    trainer_id, client_id, booking_id, pass_product_id = await _seed_completed_booking_without_pass(
        db_session, slot_date=yesterday
    )
    await db_session.execute(
        text("UPDATE bookings SET status = 'confirmed' WHERE id = :bid"),
        {"bid": booking_id},
    )
    await db_session.commit()

    issued = await issue_pass_to_client(db_session, trainer_id, client_id, pass_product_id)
    pass_instance_id = int(issued["id"])

    listed = await list_redeemable_bookings_for_pass_instance(
        db_session, trainer_id, pass_instance_id
    )
    assert "error" not in listed
    match = next(x for x in listed["items"] if int(x["booking_id"]) == booking_id)
    assert match.get("needs_complete") is True

    out = await manual_redeem_pass_for_booking(
        db_session, trainer_id, pass_instance_id, booking_id
    )
    assert out["already_redeemed"] is False
    assert out["pass"]["sessions_remaining"] == 9

    status = (
        await db_session.execute(
            text("SELECT status FROM bookings WHERE id = :bid"),
            {"bid": booking_id},
        )
    ).scalar()
    assert status == "completed"


@pytest.mark.asyncio
async def test_redeem_pass_session_idempotent_no_double_debit(db_session: AsyncSession) -> None:
    from src.application.pass_product_use_cases import redeem_pass_session_for_booking

    yesterday = date.today() - timedelta(days=1)
    trainer_id, client_id, booking_id, pass_product_id = await _seed_completed_booking_without_pass(
        db_session, slot_date=yesterday
    )
    issued = await issue_pass_to_client(db_session, trainer_id, client_id, pass_product_id)
    pass_instance_id = int(issued["id"])

    assert await redeem_pass_session_for_booking(db_session, booking_id) is True
    await db_session.commit()
    rem1 = (
        await db_session.execute(
            text("SELECT sessions_remaining FROM pass_instances WHERE id = :id"),
            {"id": pass_instance_id},
        )
    ).scalar()
    assert int(rem1) == 9

    assert await redeem_pass_session_for_booking(db_session, booking_id) is True
    await db_session.commit()
    rem2 = (
        await db_session.execute(
            text("SELECT sessions_remaining FROM pass_instances WHERE id = :id"),
            {"id": pass_instance_id},
        )
    ).scalar()
    assert int(rem2) == 9
