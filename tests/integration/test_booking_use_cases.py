"""
Integration tests for booking use cases. Require test DB (alembic upgrade head).
"""
import asyncio
from datetime import date, datetime, timedelta, time, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id

from src.application.booking_use_cases import (
    create_booking,
    generate_reminders_for_booking,
    get_bookings_pending_notification,
    list_bookings_to_complete,
    list_pending_reminders,
    mark_booking_completed_and_notify,
    mark_reminder_sent,
)
from src.infrastructure.db.session import async_session_factory


async def _create_trainer_and_slot(
    session: AsyncSession,
    slot_date: date,
    start_time: time,
    end_time: time,
    status: str = "available",
) -> tuple[int, int, int]:
    """Insert trainer + profile + trainer_services + slot. Uses seeded `services` row (no junk names)."""
    service_id = await require_seed_service_id(session)
    r = await session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    (trainer_id,) = r.fetchone()
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'Test', 'Trainer', 25)"
        ),
        {"tid": trainer_id},
    )
    await session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    r = await session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :start, :end, :status)
            RETURNING id
        """),
        {
            "tid": trainer_id,
            "d": slot_date,
            "start": start_time,
            "end": end_time,
            "status": status,
        },
    )
    (slot_id,) = r.fetchone()
    await session.commit()
    return trainer_id, slot_id, service_id


async def _create_client(session: AsyncSession, telegram_id: int) -> int:
    """Insert client. Returns client_id."""
    phone, phone_normalized = belarus_test_phone(telegram_id)
    r = await session.execute(
        text("""
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tid, 'Test', 'Client', :phone, :phone_normalized)
            RETURNING id
        """),
        {"tid": telegram_id, "phone": phone, "phone_normalized": phone_normalized},
    )
    (client_id,) = r.fetchone()
    await session.commit()
    return client_id


@pytest.mark.asyncio
async def test_create_booking_success(db_session: AsyncSession) -> None:
    """Create booking on available slot: returns id, slot becomes booked."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    booking_id = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    assert booking_id is not None
    r = await db_session.execute(text("SELECT status FROM slots WHERE id = :id"), {"id": slot_id})
    assert r.scalar() == "booked"


@pytest.mark.asyncio
async def test_create_booking_wrong_slot_returns_none(db_session: AsyncSession) -> None:
    """Wrong slot_id or trainer_id: create_booking returns None."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    wrong_slot_id = slot_id + 10_000
    booking_id = await create_booking(
        db_session,
        slot_id=wrong_slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    assert booking_id is None


@pytest.mark.asyncio
async def test_create_booking_same_slot_twice_second_fails(db_session: AsyncSession) -> None:
    """Second booking on same slot fails (slot already booked)."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    client_id_1 = await _create_client(db_session, unique_test_telegram_id())
    client_id_2 = await _create_client(db_session, unique_test_telegram_id())
    first = await create_booking(
        db_session, slot_id, trainer_id, client_id_1, service_id=service_id
    )
    assert first is not None
    second = await create_booking(
        db_session, slot_id, trainer_id, client_id_2, service_id=service_id
    )
    assert second is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_use_test_db")
async def test_create_booking_concurrent_same_slot_two_sessions_one_wins() -> None:
    """Два параллельных create_booking на один слот: блокировка строки слота, один успех.

    Setup must use the same ``async_session_factory`` as concurrent attempts (patched by
    ``app_use_test_db``). Using ``db_session`` for setup and the global factory for attempts
    crosses connections and uncommitted test data is invisible to the attempts.
    """
    tomorrow = date.today() + timedelta(days=1)
    async with async_session_factory() as session:
        trainer_id, slot_id, service_id = await _create_trainer_and_slot(
            session, tomorrow, time(10, 0), time(11, 0)
        )
        client_id_1 = await _create_client(session, unique_test_telegram_id())
        client_id_2 = await _create_client(session, unique_test_telegram_id())

    async def _attempt(client_id: int) -> int | None:
        async with async_session_factory() as session:
            return await create_booking(
                session,
                slot_id,
                trainer_id,
                client_id,
                service_id=service_id,
            )

    results = await asyncio.gather(_attempt(client_id_1), _attempt(client_id_2))
    successes = [r for r in results if r is not None]
    assert len(successes) == 1


@pytest.mark.asyncio
async def test_generate_reminders_and_list_pending(db_session: AsyncSession) -> None:
    """After create_booking + generate_reminders, reminders exist; list_pending returns due ones only."""
    # Slot in 3 days so 24h and 2h reminders are in the future — list_pending_reminders returns empty until we insert one due
    future = date.today() + timedelta(days=3)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, future, time(14, 0), time(15, 0)
    )
    client_tg = unique_test_telegram_id()
    client_id = await _create_client(db_session, client_tg)
    booking_id = await create_booking(
        db_session, slot_id, trainer_id, client_id, service_id=service_id
    )
    assert booking_id is not None
    await generate_reminders_for_booking(db_session, booking_id)

    # No reminder due yet (send_at in future)
    pending = await list_pending_reminders(db_session)
    due_for_this_booking = [p for p in pending if p.get("client_telegram_id") == client_tg]
    assert len(due_for_this_booking) == 0

    # Insert one reminder with send_at in the past
    await db_session.execute(
        text("""
            INSERT INTO reminders (booking_id, client_telegram_id, kind, send_at, status)
            VALUES (:bid, :ctg, 'before_24h', now() - interval '1 minute', 'pending')
        """),
        {"bid": booking_id, "ctg": client_tg},
    )
    await db_session.commit()

    pending = await list_pending_reminders(db_session)
    due_for_this_booking = [p for p in pending if p.get("client_telegram_id") == client_tg]
    assert len(due_for_this_booking) == 1
    assert due_for_this_booking[0]["kind"] == "before_24h"
    reminder_id = due_for_this_booking[0]["id"]

    await mark_reminder_sent(db_session, reminder_id)
    pending_after = await list_pending_reminders(db_session)
    due_after = [p for p in pending_after if p.get("client_telegram_id") == client_tg]
    assert len(due_after) == 0


@pytest.mark.asyncio
async def test_list_bookings_to_complete_and_mark_completed(db_session: AsyncSession) -> None:
    """Past-slot pending booking appears in list_bookings_to_complete; mark_booking_completed_and_notify updates status and creates notification row."""
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(9, 0), time(10, 0), status="booked"
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    r = await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc_id, 'pending')
            RETURNING id
        """),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc_id": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    to_complete = await list_bookings_to_complete(db_session)
    ids = [b["id"] for b in to_complete]
    assert booking_id in ids

    await mark_booking_completed_and_notify(db_session, booking_id)

    r = await db_session.execute(text("SELECT status FROM bookings WHERE id = :id"), {"id": booking_id})
    assert r.scalar() == "completed"
    r = await db_session.execute(
        text("SELECT 1 FROM booking_completed_notifications WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert r.fetchone() is not None


@pytest.mark.asyncio
async def test_trainer_created_booking_not_in_trainer_pending_notification_queue(
    db_session: AsyncSession,
) -> None:
    """Trainer-initiated bookings are confirmed; they must not be queued for confirm/decline push."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    bid_trainer = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert bid_trainer is not None

    # Second slot for client-initiated pending booking (different time)
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :start, :end, 'available')
            RETURNING id
        """),
        {"tid": trainer_id, "d": tomorrow, "start": time(12, 0), "end": time(13, 0)},
    )
    (slot_id_2,) = r.fetchone()
    await db_session.commit()
    client_id_2 = await _create_client(db_session, unique_test_telegram_id())
    bid_client = await create_booking(
        db_session,
        slot_id=slot_id_2,
        trainer_id=trainer_id,
        client_id=client_id_2,
        service_id=service_id,
        created_by_trainer=False,
    )
    assert bid_client is not None

    pending = await get_bookings_pending_notification(db_session)
    ids = [b["id"] for b in pending]
    assert bid_trainer not in ids
    assert bid_client in ids
