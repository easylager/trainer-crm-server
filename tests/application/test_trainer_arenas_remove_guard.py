"""Removing a venue from trainer profile is blocked while current/future bookings resolve to it."""
from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.trainer_use_cases import (
    create_trainer,
    ensure_trainer_arenas_replace_allowed,
    list_trainer_arena_ids_locked_by_bookings,
    update_trainer_profile,
)
from tests.conftest import belarus_test_phone, unique_test_telegram_id


async def _two_arenas_same_city(session) -> tuple[int, int, int]:
    r = await session.execute(
        text(
            """
            SELECT a.id, a.city_id FROM arenas a
            WHERE a.is_active IS TRUE AND a.city_id IS NOT NULL
            ORDER BY a.id
            LIMIT 1
            """
        )
    )
    row = r.fetchone()
    if row is None:
        pytest.skip("need arena")
    arena_a, city_id = int(row[0]), int(row[1])
    r2 = await session.execute(
        text(
            """
            SELECT id FROM arenas
            WHERE city_id = :cid AND id <> :aid AND is_active IS TRUE
            ORDER BY id LIMIT 1
            """
        ),
        {"cid": city_id, "aid": arena_a},
    )
    row2 = r2.fetchone()
    if row2 is None:
        r3 = await session.execute(
            text(
                """
                INSERT INTO arenas (city_id, name, is_active)
                VALUES (:cid, 'Arena remove-guard B', true)
                RETURNING id
                """
            ),
            {"cid": city_id},
        )
        arena_b = int(r3.scalar())
    else:
        arena_b = int(row2[0])
    return arena_a, arena_b, city_id


async def _insert_client(session) -> int:
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    return int(r.scalar())


async def _seed_booking(
    session,
    *,
    trainer_id: int,
    service_id: int,
    arena_id: int,
    slot_date: date,
    status: str = "confirmed",
    start: time = time(10, 0),
    end: time = time(11, 0),
) -> None:
    r = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, arena_id)
            VALUES (:tid, :d, :st, :et, 'booked', 1, :aid)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date, "st": start, "et": end, "aid": arena_id},
    )
    slot_id = int(r.scalar())
    client_id = await _insert_client(session)
    await session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, arena_id)
            VALUES (:sid, :tid, :cid, :svc, :st, :aid)
            """
        ),
        {
            "sid": slot_id,
            "tid": trainer_id,
            "cid": client_id,
            "svc": service_id,
            "st": status,
            "aid": arena_id,
        },
    )


@pytest.mark.asyncio
async def test_locked_arena_ids_from_future_booking(db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    if sid is None:
        pytest.skip("need service")
    arena_a, arena_b, _city = await _two_arenas_same_city(db_session)
    tid = await create_trainer(
        db_session,
        profile={"first_name": "A", "last_name": "B", "age": 30},
        service_ids=[int(sid)],
        arena_ids=[arena_a, arena_b],
    )
    await _seed_booking(
        db_session,
        trainer_id=tid,
        service_id=int(sid),
        arena_id=arena_a,
        slot_date=date.today() + timedelta(days=3),
    )
    await db_session.commit()

    locked = await list_trainer_arena_ids_locked_by_bookings(db_session, tid)
    assert arena_a in locked
    assert arena_b not in locked


@pytest.mark.asyncio
async def test_cannot_remove_arena_with_future_booking(db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    if sid is None:
        pytest.skip("need service")
    arena_a, arena_b, _city = await _two_arenas_same_city(db_session)
    tid = await create_trainer(
        db_session,
        profile={"first_name": "C", "last_name": "D", "age": 28},
        service_ids=[int(sid)],
        arena_ids=[arena_a, arena_b],
    )
    await _seed_booking(
        db_session,
        trainer_id=tid,
        service_id=int(sid),
        arena_id=arena_a,
        slot_date=date.today() + timedelta(days=5),
        status="pending",
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="записи"):
        await ensure_trainer_arenas_replace_allowed(
            db_session, tid, [arena_b], replace_city_ids=None
        )

    await ensure_trainer_arenas_replace_allowed(
        db_session, tid, [arena_a], replace_city_ids=None
    )


@pytest.mark.asyncio
async def test_update_trainer_profile_raises_when_removing_booked_arena(db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    if sid is None:
        pytest.skip("need service")
    arena_a, arena_b, city_id = await _two_arenas_same_city(db_session)
    tid = await create_trainer(
        db_session,
        profile={"first_name": "E", "last_name": "F", "age": 32, "city_id": city_id},
        service_ids=[int(sid)],
        arena_ids=[arena_a, arena_b],
    )
    await _seed_booking(
        db_session,
        trainer_id=tid,
        service_id=int(sid),
        arena_id=arena_a,
        slot_date=date.today() + timedelta(days=2),
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="записи"):
        await update_trainer_profile(db_session, tid, profile={}, arena_ids=[arena_b])


@pytest.mark.asyncio
async def test_past_booking_does_not_lock_arena(db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    if sid is None:
        pytest.skip("need service")
    arena_a, arena_b, city_id = await _two_arenas_same_city(db_session)
    tid = await create_trainer(
        db_session,
        profile={"first_name": "G", "last_name": "H", "age": 35, "city_id": city_id},
        service_ids=[int(sid)],
        arena_ids=[arena_a, arena_b],
    )
    await _seed_booking(
        db_session,
        trainer_id=tid,
        service_id=int(sid),
        arena_id=arena_a,
        slot_date=date.today() - timedelta(days=2),
    )
    await db_session.commit()

    locked = await list_trainer_arena_ids_locked_by_bookings(db_session, tid)
    assert arena_a not in locked
    await update_trainer_profile(db_session, tid, profile={}, arena_ids=[arena_b])
