"""
E2E: full booking lifecycle — create → complete → client feedback → trainer feedback.
No Telegram; only DB and use cases.
"""
from datetime import date, timedelta, time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    get_booking_for_client_feedback,
    get_booking_for_trainer_feedback,
    list_bookings_to_complete,
    mark_booking_completed_and_notify,
    set_booking_trainer_review,
)
from src.application.trainer_use_cases import add_trainer_rating


async def _create_trainer_slot_and_pending_booking(
    session: AsyncSession,
    client_telegram_id: int,
    slot_date: date,
    start_time: time,
    end_time: time,
) -> tuple[int, int, int]:
    """Create trainer + profile + slot (booked) + pending booking. Returns (trainer_id, slot_id, booking_id)."""
    r = await session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    (trainer_id,) = r.fetchone()
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'E2E', 'Trainer', 30)"
        ),
        {"tid": trainer_id},
    )
    r = await session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :start, :end, 'booked')
            RETURNING id
        """),
        {"tid": trainer_id, "d": slot_date, "start": start_time, "end": end_time},
    )
    (slot_id,) = r.fetchone()
    r = await session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_telegram_id, client_phone, status)
            VALUES (:sid, :tid, :ctid, '+375299999999', 'pending')
            RETURNING id
        """),
        {"sid": slot_id, "tid": trainer_id, "ctid": client_telegram_id},
    )
    (booking_id,) = r.fetchone()
    await session.commit()
    return trainer_id, slot_id, booking_id


@pytest.mark.asyncio
async def test_booking_complete_flow_with_feedback(db_session: AsyncSession) -> None:
    """
    Full flow: past-slot pending booking → complete → notification row →
    client rating+review → trainer review; assert DB state at the end.
    """
    yesterday = date.today() - timedelta(days=1)
    client_telegram_id = 888777666
    trainer_id, slot_id, booking_id = await _create_trainer_slot_and_pending_booking(
        db_session,
        client_telegram_id,
        yesterday,
        time(9, 0),
        time(10, 0),
    )

    to_complete = await list_bookings_to_complete(db_session)
    assert any(b["id"] == booking_id for b in to_complete), "our booking should be in to_complete"

    await mark_booking_completed_and_notify(db_session, booking_id)

    r = await db_session.execute(text("SELECT status FROM bookings WHERE id = :id"), {"id": booking_id})
    assert r.scalar() == "completed"
    r = await db_session.execute(
        text("SELECT 1 FROM booking_completed_notifications WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert r.fetchone() is not None

    booking_for_client = await get_booking_for_client_feedback(
        db_session, booking_id, client_telegram_id
    )
    assert booking_for_client is not None
    assert booking_for_client["trainer_id"] == trainer_id

    ok = await add_trainer_rating(
        db_session, trainer_id, client_telegram_id,
        rating=5,
        review_text="E2E client review",
    )
    assert ok is True

    booking_for_trainer = await get_booking_for_trainer_feedback(
        db_session, booking_id, trainer_id
    )
    assert booking_for_trainer is not None

    ok = await set_booking_trainer_review(
        db_session, booking_id, trainer_id,
        "E2E trainer review",
    )
    assert ok is True

    r = await db_session.execute(
        text("SELECT rating, review_text FROM trainer_ratings WHERE trainer_id = :tid AND client_telegram_id = :ctid"),
        {"tid": trainer_id, "ctid": client_telegram_id},
    )
    row = r.fetchone()
    assert row is not None
    assert row[0] == 5
    assert row[1] == "E2E client review"

    r = await db_session.execute(
        text("SELECT trainer_review_text FROM bookings WHERE id = :id"),
        {"id": booking_id},
    )
    assert r.scalar() == "E2E trainer review"
