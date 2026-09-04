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
    INACTIVE_KIND_10_DAYS,
    cancel_booking,
    confirm_booking,
    create_booking,
    generate_reminders_for_booking,
    get_bookings_pending_notification,
    get_clients_for_inactive_notification,
    claim_client_trainer_booked_notification,
    get_pending_booking_confirmed_notifications,
    get_pending_trainer_booked_notifications,
    list_bookings_to_complete,
    list_pending_reminders,
    mark_booking_completed_and_notify,
    mark_booking_confirmed_notified,
    mark_reminder_sent,
)
from src.infrastructure.repositories import TrainerRepository


async def _create_trainer_and_slot(
    session: AsyncSession,
    slot_date: date,
    start_time: time,
    end_time: time,
    status: str = "available",
    *,
    capacity: int = 1,
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
    if capacity > 1:
        r = await session.execute(
            text("""
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
                VALUES (:tid, :d, :start, :end, :status, :capacity, :sid)
                RETURNING id
            """),
            {
                "tid": trainer_id,
                "d": slot_date,
                "start": start_time,
                "end": end_time,
                "status": status,
                "capacity": capacity,
                "sid": service_id,
            },
        )
    else:
        r = await session.execute(
            text("""
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
                VALUES (:tid, :d, :start, :end, :status, :capacity)
                RETURNING id
            """),
            {
                "tid": trainer_id,
                "d": slot_date,
                "start": start_time,
                "end": end_time,
                "status": status,
                "capacity": capacity,
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
    booking_id, _ = await create_booking(
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
    booking_id, _ = await create_booking(
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
    first, _ = await create_booking(
        db_session, slot_id, trainer_id, client_id_1, service_id=service_id
    )
    assert first is not None
    second, _ = await create_booking(
        db_session, slot_id, trainer_id, client_id_2, service_id=service_id
    )
    assert second is None


@pytest.mark.asyncio
async def test_create_booking_concurrent_same_slot_two_sessions_one_wins() -> None:
    """Два параллельных create_booking на один слот: блокировка строки слота, один успех.

    Dedicated engine with real commits — patched single-connection test fixture cannot
    run two concurrent queries on the same asyncpg connection.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.shared.config import Settings

    settings = Settings()
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        tomorrow = date.today() + timedelta(days=1)
        async with factory() as session:
            trainer_id, slot_id, service_id = await _create_trainer_and_slot(
                session, tomorrow, time(10, 0), time(11, 0)
            )
            client_id_1 = await _create_client(session, unique_test_telegram_id())
            client_id_2 = await _create_client(session, unique_test_telegram_id())

        async def _attempt(client_id: int) -> int | None:
            async with factory() as session:
                bid, _flags = await create_booking(
                    session,
                    slot_id,
                    trainer_id,
                    client_id,
                    service_id=service_id,
                )
                return bid

        results = await asyncio.gather(_attempt(client_id_1), _attempt(client_id_2))
        successes = [r for r in results if r is not None]
        assert len(successes) == 1
    finally:
        await engine.dispose()


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
    booking_id, _ = await create_booking(
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
async def test_same_day_two_bookings_merged_reminder_schedule(db_session: AsyncSession) -> None:
    """Two bookings same calendar day → still two pending kinds (e.g. 24h + 2h), not four; merged_booking_ids set."""
    day = date.today() + timedelta(days=3)
    trainer_id, slot1, service_id = await _create_trainer_and_slot(
        db_session, day, time(10, 0), time(11, 0)
    )
    r_slot2 = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, :st, :en, 'available', 1)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": day,
            "st": time(14, 0),
            "en": time(15, 0),
        },
    )
    slot2 = int(r_slot2.scalar_one())
    await db_session.commit()
    client_tg = unique_test_telegram_id()
    client_id = await _create_client(db_session, client_tg)
    b1, _ = await create_booking(
        db_session, slot1, trainer_id, client_id, service_id=service_id
    )
    assert b1 is not None
    await generate_reminders_for_booking(db_session, b1)
    r = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM reminders WHERE client_telegram_id = :t AND status = 'pending'"
        ),
        {"t": client_tg},
    )
    assert int(r.scalar() or 0) == 2
    b2, _ = await create_booking(
        db_session, slot2, trainer_id, client_id, service_id=service_id
    )
    assert b2 is not None
    await generate_reminders_for_booking(db_session, b2)
    r2 = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM reminders WHERE client_telegram_id = :t AND status = 'pending'"
        ),
        {"t": client_tg},
    )
    assert int(r2.scalar() or 0) == 2
    r3 = await db_session.execute(
        text(
            """
            SELECT booking_id, merged_booking_ids, kind
            FROM reminders
            WHERE client_telegram_id = :t AND status = 'pending'
            ORDER BY kind
            """
        ),
        {"t": client_tg},
    )
    mrows = r3.fetchall()
    assert len(mrows) == 2
    assert all(int(row[0]) == int(b1) for row in mrows)
    kinds = {row[2] for row in mrows}
    assert "before_24h" in kinds and "before_2h" in kinds
    merged = mrows[0][1]
    assert merged is not None
    assert [int(x) for x in list(merged)] == [int(b2)]


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
async def test_list_bookings_to_complete_excludes_booking_problem_report(
    db_session: AsyncSession,
) -> None:
    """E4 T4.5: reported problems must not enter auto-complete queue."""
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
    await db_session.execute(
        text(
            """
            INSERT INTO booking_problem_reports
                (booking_id, trainer_id, client_id, preset_id, payment_class, note, source)
            VALUES (:bid, :tid, :cid, 'A1', 'NONE', NULL, 'test')
            """
        ),
        {"bid": booking_id, "tid": trainer_id, "cid": client_id},
    )
    await db_session.commit()

    to_complete = await list_bookings_to_complete(db_session)
    ids = [b["id"] for b in to_complete]
    assert booking_id not in ids


@pytest.mark.asyncio
async def test_mark_booking_completed_skips_when_problem_report_exists(db_session: AsyncSession) -> None:
    """E4: completion worker must not treat bookings that already have a problem report."""
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(9, 0), time(10, 0), status="booked"
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc_id, 'pending')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc_id": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO booking_problem_reports
                (booking_id, trainer_id, client_id, preset_id, payment_class, note, source)
            VALUES (:bid, :tid, :cid, 'A1', 'NONE', NULL, 'test')
            """
        ),
        {"bid": booking_id, "tid": trainer_id, "cid": client_id},
    )
    await db_session.commit()

    result = await mark_booking_completed_and_notify(db_session, booking_id)
    assert result is False
    r = await db_session.execute(text("SELECT status FROM bookings WHERE id = :id"), {"id": booking_id})
    assert r.scalar() == "pending"


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
    bid_trainer, _ = await create_booking(
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
    bid_client, _ = await create_booking(
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


@pytest.mark.asyncio
async def test_group_slot_first_booking_keeps_slot_available(db_session: AsyncSession) -> None:
    """capacity=2: first booking leaves slot available until capacity is full."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0), capacity=2
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    bid, _ = await create_booking(db_session, slot_id, trainer_id, client_id, service_id=service_id)
    assert bid is not None
    r = await db_session.execute(text("SELECT status FROM slots WHERE id = :id"), {"id": slot_id})
    assert r.scalar() == "available"


@pytest.mark.asyncio
async def test_group_slot_second_booking_then_booked(db_session: AsyncSession) -> None:
    """capacity=2: two bookings fill the slot (status booked)."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0), capacity=2
    )
    c1 = await _create_client(db_session, unique_test_telegram_id())
    c2 = await _create_client(db_session, unique_test_telegram_id())
    assert (await create_booking(db_session, slot_id, trainer_id, c1, service_id=service_id))[0] is not None
    assert (await create_booking(db_session, slot_id, trainer_id, c2, service_id=service_id))[0] is not None
    r = await db_session.execute(text("SELECT status FROM slots WHERE id = :id"), {"id": slot_id})
    assert r.scalar() == "booked"


@pytest.mark.asyncio
async def test_group_slot_booking_price_uses_group_override(db_session: AsyncSession) -> None:
    """Group slot snapshot uses COALESCE(group_price_cents, anchor), not tier variants."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0), capacity=2
    )
    repo = TrainerRepository(db_session)
    await repo.set_trainer_services(
        trainer_id,
        [(service_id, [("adult", 8000), ("child", 5000)], None, 3500)],
    )
    await db_session.commit()
    client_id = await _create_client(db_session, unique_test_telegram_id())
    bid, _ = await create_booking(db_session, slot_id, trainer_id, client_id, service_id=service_id)
    assert bid is not None
    r = await db_session.execute(
        text("SELECT booking_price_cents FROM bookings WHERE id = :id"), {"id": bid}
    )
    assert int(r.scalar()) == 3500


@pytest.mark.asyncio
async def test_group_slot_third_booking_rejected(db_session: AsyncSession) -> None:
    """capacity=2: third client cannot book the same slot."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0), capacity=2
    )
    c1 = await _create_client(db_session, unique_test_telegram_id())
    c2 = await _create_client(db_session, unique_test_telegram_id())
    c3 = await _create_client(db_session, unique_test_telegram_id())
    assert (await create_booking(db_session, slot_id, trainer_id, c1, service_id=service_id))[0] is not None
    assert (await create_booking(db_session, slot_id, trainer_id, c2, service_id=service_id))[0] is not None
    third, _ = await create_booking(db_session, slot_id, trainer_id, c3, service_id=service_id)
    assert third is None


@pytest.mark.asyncio
async def test_group_slot_cancel_frees_space(db_session: AsyncSession) -> None:
    """After cancel, slot becomes available again and another client can book."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0), capacity=2
    )
    c1 = await _create_client(db_session, unique_test_telegram_id())
    c2 = await _create_client(db_session, unique_test_telegram_id())
    c3 = await _create_client(db_session, unique_test_telegram_id())
    assert (await create_booking(db_session, slot_id, trainer_id, c1, service_id=service_id))[0] is not None
    bid2, _ = await create_booking(db_session, slot_id, trainer_id, c2, service_id=service_id)
    assert bid2 is not None
    r = await db_session.execute(text("SELECT status FROM slots WHERE id = :id"), {"id": slot_id})
    assert r.scalar() == "booked"
    ok = await cancel_booking(db_session, bid2, trainer_id)
    assert ok is True
    r = await db_session.execute(text("SELECT status FROM slots WHERE id = :id"), {"id": slot_id})
    assert r.scalar() == "available"
    third, _ = await create_booking(db_session, slot_id, trainer_id, c3, service_id=service_id)
    assert third is not None


@pytest.mark.asyncio
async def test_confirm_pending_sets_client_trainer_booked_notified_no_duplicate_queue(
    db_session: AsyncSession,
) -> None:
    """
    Trainer confirm sends the rich client push separately (only after it actually succeeds —
    see mark_booking_confirmed_notified); confirm_booking itself must not enqueue the «Вас
    записали» fallback loop for the same booking (it touches notified_at to close that race
    even before the confirm push is sent — see confirm_booking's own docstring).
    """
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    booking_id, _ = await create_booking(
        db_session,
        slot_id,
        trainer_id,
        client_id,
        service_id=service_id,
        created_by_trainer=False,
    )
    assert booking_id is not None
    r0 = await db_session.execute(
        text("SELECT client_notified_trainer_booked_at, notified_at FROM bookings WHERE id = :id"),
        {"id": booking_id},
    )
    row0 = r0.fetchone()
    assert row0[0] is None
    assert row0[1] is None
    info = await confirm_booking(db_session, booking_id, trainer_id)
    assert info is not None
    r1 = await db_session.execute(
        text("SELECT client_notified_trainer_booked_at, notified_at FROM bookings WHERE id = :id"),
        {"id": booking_id},
    )
    row1 = r1.fetchone()
    assert row1[0] is None, "not notified yet — only a successful send may set this"
    assert row1[1] is not None, "confirm_booking must touch notified_at to close the race with the other loop"
    pending = await get_pending_trainer_booked_notifications(db_session, limit=50)
    assert all(int(p["booking_id"]) != int(booking_id) for p in pending)

    await mark_booking_confirmed_notified(db_session, booking_id)
    r2 = await db_session.execute(
        text("SELECT client_notified_trainer_booked_at FROM bookings WHERE id = :id"),
        {"id": booking_id},
    )
    assert r2.scalar() is not None


@pytest.mark.asyncio
async def test_pending_booking_confirmed_notifications_retries_undelivered_confirm_push(
    db_session: AsyncSession,
) -> None:
    """
    Regression: a booking confirm_booking marked confirmed but whose «Ваша запись подтверждена»
    push never went out (e.g. run_booking_confirmed_notifier_loop's earlier retry attempt failed
    too) must keep showing up here — this is the safety net that used to be missing entirely,
    the client was just never notified once client_notified_trainer_booked_at got set regardless
    of send success.
    """
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(12, 0), time(13, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    booking_id, _ = await create_booking(
        db_session,
        slot_id,
        trainer_id,
        client_id,
        service_id=service_id,
        created_by_trainer=False,
    )
    assert booking_id is not None
    info = await confirm_booking(db_session, booking_id, trainer_id)
    assert info is not None

    pending = await get_pending_booking_confirmed_notifications(db_session, limit=50)
    ids = [int(p["id"]) for p in pending]
    assert int(booking_id) in ids
    row = next(p for p in pending if int(p["id"]) == int(booking_id))
    assert int(row["trainer_id"]) == int(trainer_id)
    assert row["client_telegram_id"] is not None

    await mark_booking_confirmed_notified(db_session, booking_id)
    pending_after = await get_pending_booking_confirmed_notifications(db_session, limit=50)
    assert all(int(p["id"]) != int(booking_id) for p in pending_after)


@pytest.mark.asyncio
async def test_notify_client_booking_confirmed_returns_false_on_send_failure(
    db_session: AsyncSession,
) -> None:
    """Send failure must return False, not raise — callers rely on this to decide whether to retry."""
    from unittest.mock import AsyncMock, patch

    from src.application.booking_confirm_client_notify import notify_client_booking_confirmed_by_trainer

    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(9, 0), time(10, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    booking_id, _ = await create_booking(
        db_session, slot_id, trainer_id, client_id, service_id=service_id, created_by_trainer=False
    )
    assert booking_id is not None
    info = await confirm_booking(db_session, booking_id, trainer_id)
    assert info is not None

    with patch("src.application.booking_confirm_client_notify.Bot") as MockBot:
        inst = MockBot.return_value
        inst.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
        inst.session = AsyncMock()
        inst.session.close = AsyncMock()
        ok = await notify_client_booking_confirmed_by_trainer(db_session, trainer_id, booking_id, info)
    assert ok is False

    with patch("src.application.booking_confirm_client_notify.Bot") as MockBot:
        inst = MockBot.return_value
        inst.send_message = AsyncMock()
        inst.session = AsyncMock()
        inst.session.close = AsyncMock()
        ok2 = await notify_client_booking_confirmed_by_trainer(db_session, trainer_id, booking_id, info)
    assert ok2 is True


@pytest.mark.asyncio
async def test_trainer_booked_queue_skips_when_trainer_was_notified_pending(
    db_session: AsyncSession,
) -> None:
    """If booking went through trainer pending push (notified_at set), never queue «Вас записали…»."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(15, 15), time(16, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    booking_id, _ = await create_booking(
        db_session,
        slot_id,
        trainer_id,
        client_id,
        service_id=service_id,
        created_by_trainer=False,
    )
    assert booking_id is not None
    await db_session.execute(
        text(
            """
            UPDATE bookings
            SET status = 'confirmed', notified_at = NOW(), client_notified_trainer_booked_at = NULL
            WHERE id = :id
            """
        ),
        {"id": booking_id},
    )
    await db_session.commit()
    pending = await get_pending_trainer_booked_notifications(db_session, limit=50)
    assert all(int(p["booking_id"]) != int(booking_id) for p in pending)


@pytest.mark.asyncio
async def test_trainer_booked_claim_is_idempotent(
    db_session: AsyncSession,
) -> None:
    """API and notification_service must not both deliver «Вас записали…» for one booking."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(17, 0), time(18, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    booking_id, _ = await create_booking(
        db_session,
        slot_id,
        trainer_id,
        client_id,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert booking_id is not None
    assert await claim_client_trainer_booked_notification(db_session, int(booking_id)) is True
    assert await claim_client_trainer_booked_notification(db_session, int(booking_id)) is False
    pending = await get_pending_trainer_booked_notifications(db_session, limit=50)
    assert all(int(p["booking_id"]) != int(booking_id) for p in pending)


@pytest.mark.asyncio
async def test_trainer_booked_queue_includes_trainer_created_confirmed(
    db_session: AsyncSession,
) -> None:
    """Trainer-initiated confirmed row: no pending push → notified_at NULL → queue until client push sent."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(16, 30), time(17, 15)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    booking_id, _ = await create_booking(
        db_session,
        slot_id,
        trainer_id,
        client_id,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert booking_id is not None
    pending = await get_pending_trainer_booked_notifications(db_session, limit=50)
    ids = [int(p["booking_id"]) for p in pending]
    assert int(booking_id) in ids


@pytest.mark.asyncio
async def test_inactive_client_10_days_excludes_client_with_future_booking(
    db_session: AsyncSession,
) -> None:
    """Future booking means the latest session is in future, so client is active."""
    client_id = await _create_client(db_session, unique_test_telegram_id())

    trainer_past, slot_past, service_past = await _create_trainer_and_slot(
        db_session,
        date.today() - timedelta(days=10),
        time(9, 0),
        time(10, 0),
        status="booked",
    )
    trainer_future, slot_future, service_future = await _create_trainer_and_slot(
        db_session,
        date.today() + timedelta(days=5),
        time(11, 0),
        time(12, 0),
        status="booked",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES
                (:slot_past, :trainer_past, :client_id, :service_past, 'confirmed'),
                (:slot_future, :trainer_future, :client_id, :service_future, 'confirmed')
            """
        ),
        {
            "slot_past": slot_past,
            "trainer_past": trainer_past,
            "service_past": service_past,
            "slot_future": slot_future,
            "trainer_future": trainer_future,
            "service_future": service_future,
            "client_id": client_id,
        },
    )
    await db_session.commit()

    clients = await get_clients_for_inactive_notification(
        db_session, INACTIVE_KIND_10_DAYS
    )
    ids = {int(c["client_id"]) for c in clients}
    assert client_id not in ids


@pytest.mark.asyncio
async def test_inactive_client_10_days_includes_after_last_session_passes(
    db_session: AsyncSession,
) -> None:
    """Client appears exactly 10 days after the latest overall session has ended."""
    client_id = await _create_client(db_session, unique_test_telegram_id())
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session,
        date.today() - timedelta(days=10),
        time(8, 0),
        time(9, 0),
        status="booked",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:slot_id, :trainer_id, :client_id, :service_id, 'confirmed')
            """
        ),
        {
            "slot_id": slot_id,
            "trainer_id": trainer_id,
            "service_id": service_id,
            "client_id": client_id,
        },
    )
    await db_session.commit()

    clients = await get_clients_for_inactive_notification(
        db_session, INACTIVE_KIND_10_DAYS
    )
    ids = {int(c["client_id"]) for c in clients}
    assert client_id in ids
