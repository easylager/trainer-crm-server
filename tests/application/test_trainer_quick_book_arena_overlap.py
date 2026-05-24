"""Trainer quick-book: free overlapping slots must not block another venue or interval."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import create_booking, create_trainer_quick_booking
from src.application.trainer_schedule_use_cases import ensure_individual_slot_for_quick_book
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


async def _two_arena_ids(session: AsyncSession) -> tuple[int, int]:
    r = await session.execute(
        text(
            """
            SELECT id FROM arenas
            WHERE COALESCE(is_active, true)
            ORDER BY id
            LIMIT 2
            """
        )
    )
    rows = r.fetchall()
    if len(rows) < 2:
        pytest.skip("Need at least two seeded arenas")
    return int(rows[0][0]), int(rows[1][0])


async def _seed_trainer_with_two_arenas(session: AsyncSession) -> tuple[int, int, int, int]:
    arena_a, arena_b = await _two_arena_ids(session)
    service_id = await require_seed_service_id(session)
    _, city_id, _ = await require_seed_arena_city_name(session)
    r = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    trainer_id = int(r.scalar_one())
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id) "
            "VALUES (:tid, 'Quick', 'Book', 30, :cid)"
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    for aid in (arena_a, arena_b):
        await session.execute(
            text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
            {"tid": trainer_id, "aid": aid},
        )
    await session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_a, "tid": trainer_id},
    )
    await session.commit()
    return trainer_id, service_id, arena_a, arena_b


async def _create_client(session: AsyncSession) -> int:
    tid = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tid)
    r = await session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": tid, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await session.commit()
    return int(client_id)


async def _insert_individual_slot(
    session: AsyncSession,
    trainer_id: int,
    slot_date: date,
    start_h: int,
    start_m: int,
    end_h: int,
    end_m: int,
    *,
    arena_id: int | None,
    status: str = "available",
) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, arena_id)
            VALUES (:tid, :d, :st, :en, :status, 1, :aid)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": slot_date,
            "st": time(start_h, start_m),
            "en": time(end_h, end_m),
            "status": status,
            "aid": arena_id,
        },
    )
    (slot_id,) = r.fetchone()
    await session.commit()
    return int(slot_id)


@pytest.mark.asyncio
async def test_quick_book_same_interval_different_arena_updates_slot(db_session: AsyncSession) -> None:
    trainer_id, service_id, arena_a, arena_b = await _seed_trainer_with_two_arenas(db_session)
    client_id = await _create_client(db_session)
    slot_date = date.today() + timedelta(days=21)
    existing_id = await _insert_individual_slot(
        db_session,
        trainer_id,
        slot_date,
        10,
        0,
        11,
        0,
        arena_id=arena_a,
    )

    slot_id = await ensure_individual_slot_for_quick_book(
        db_session,
        trainer_id,
        slot_date,
        10 * 60,
        duration_minutes=60,
        arena_id=arena_b,
    )
    assert slot_id == existing_id

    r = await db_session.execute(text("SELECT arena_id FROM slots WHERE id = :id"), {"id": slot_id})
    assert int(r.scalar_one()) == arena_b

    booking_id, _mile = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
        arena_id=arena_b,
    )
    assert booking_id is not None


@pytest.mark.asyncio
async def test_quick_book_partial_overlap_removes_empty_slot(db_session: AsyncSession) -> None:
    trainer_id, service_id, arena_a, _arena_b = await _seed_trainer_with_two_arenas(db_session)
    client_id = await _create_client(db_session)
    slot_date = date.today() + timedelta(days=22)
    old_id = await _insert_individual_slot(
        db_session,
        trainer_id,
        slot_date,
        15,
        0,
        16,
        0,
        arena_id=arena_a,
    )

    result = await create_trainer_quick_booking(
        db_session,
        trainer_id=trainer_id,
        slot_date=slot_date,
        start_minutes=15 * 60 + 15,
        duration_minutes=60,
        client_id=client_id,
        service_id=service_id,
        arena_id=arena_a,
    )
    assert result is not None
    booking_id, new_slot_id, _, _ = result
    assert booking_id > 0
    assert new_slot_id != old_id

    r_old = await db_session.execute(text("SELECT 1 FROM slots WHERE id = :id"), {"id": old_id})
    assert r_old.fetchone() is None

    r_new = await db_session.execute(
        text(
            """
            SELECT EXTRACT(HOUR FROM start_time)::int * 60 + EXTRACT(MINUTE FROM start_time)::int,
                   EXTRACT(HOUR FROM end_time)::int * 60 + EXTRACT(MINUTE FROM end_time)::int
            FROM slots WHERE id = :id
            """
        ),
        {"id": new_slot_id},
    )
    sm, em = r_new.fetchone()
    assert int(sm) == 15 * 60 + 15
    assert int(em) == 16 * 60 + 15


@pytest.mark.asyncio
async def test_quick_book_overlap_with_booked_slot_still_blocked(db_session: AsyncSession) -> None:
    trainer_id, service_id, arena_a, arena_b = await _seed_trainer_with_two_arenas(db_session)
    client_id = await _create_client(db_session)
    slot_date = date.today() + timedelta(days=23)
    booked_slot_id = await _insert_individual_slot(
        db_session,
        trainer_id,
        slot_date,
        12,
        0,
        13,
        0,
        arena_id=arena_a,
    )
    other_client = await _create_client(db_session)
    bid, _ = await create_booking(
        db_session,
        slot_id=booked_slot_id,
        trainer_id=trainer_id,
        client_id=other_client,
        service_id=service_id,
        created_by_trainer=True,
        arena_id=arena_a,
    )
    assert bid is not None

    with pytest.raises(ValueError, match="занят"):
        await ensure_individual_slot_for_quick_book(
            db_session,
            trainer_id,
            slot_date,
            12 * 60,
            duration_minutes=60,
            arena_id=arena_b,
        )

    with pytest.raises(ValueError, match="занят"):
        await ensure_individual_slot_for_quick_book(
            db_session,
            trainer_id,
            slot_date,
            12 * 60 + 15,
            duration_minutes=60,
            arena_id=arena_b,
        )


@pytest.mark.asyncio
async def test_quick_book_partial_overlap_same_arena_1245_vs_1300_slot(db_session: AsyncSession) -> None:
    """12:45 session may replace empty 13:00 slot on the same venue."""
    trainer_id, service_id, arena_a, _arena_b = await _seed_trainer_with_two_arenas(db_session)
    client_id = await _create_client(db_session)
    slot_date = date.today() + timedelta(days=24)
    old_id = await _insert_individual_slot(
        db_session,
        trainer_id,
        slot_date,
        13,
        0,
        14,
        0,
        arena_id=arena_a,
    )

    result = await create_trainer_quick_booking(
        db_session,
        trainer_id=trainer_id,
        slot_date=slot_date,
        start_minutes=12 * 60 + 45,
        duration_minutes=60,
        client_id=client_id,
        service_id=service_id,
        arena_id=arena_a,
        allow_off_grid_interval=True,
    )
    assert result is not None
    _, new_slot_id, _, _ = result

    r_old = await db_session.execute(text("SELECT 1 FROM slots WHERE id = :id"), {"id": old_id})
    assert r_old.fetchone() is None

    r_new = await db_session.execute(
        text(
            """
            SELECT EXTRACT(HOUR FROM start_time)::int * 60 + EXTRACT(MINUTE FROM start_time)::int
            FROM slots WHERE id = :id
            """
        ),
        {"id": new_slot_id},
    )
    assert int(r_new.scalar_one()) == 12 * 60 + 45
