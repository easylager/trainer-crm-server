"""
Trainer «same time next week» after completed session (slot_date + 7 days).
Requires test DB with seeds (services, arenas).
"""
from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import trainer_repeat_booking_same_time_next_week

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


async def _seed_trainer_with_arena(db_session) -> tuple[int, int, int]:
    """trainer_id, service_id, arena_id."""
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'Tr', 'Te', 30, :cid)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_id, "tid": trainer_id},
    )
    await db_session.commit()
    return trainer_id, service_id, arena_id


@pytest.mark.asyncio
async def test_trainer_repeat_creates_booking_on_slot_date_plus_7(db_session) -> None:
    trainer_id, service_id, _arena_id = await _seed_trainer_with_arena(db_session)
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    past = date.today() - timedelta(days=2)
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked', :aid)
            RETURNING id
        """),
        {"tid": trainer_id, "d": past, "aid": _arena_id},
    )
    (slot_id,) = r.fetchone()
    r = await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            RETURNING id
        """),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    out = await trainer_repeat_booking_same_time_next_week(db_session, booking_id, trainer_id)
    assert out.get("success") is True
    new_id = out.get("new_booking_id")
    assert isinstance(new_id, int)
    target = past + timedelta(days=7)
    r2 = await db_session.execute(
        text("""
            SELECT s.slot_date, s.start_time, b.status
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :id
        """),
        {"id": new_id},
    )
    row = r2.fetchone()
    assert row is not None
    assert row[0] == target
    assert row[1] == time(10, 0)
    assert (row[2] or "").strip() == "confirmed"


@pytest.mark.asyncio
async def test_trainer_repeat_slot_booked_returns_error(db_session) -> None:
    trainer_id, service_id, arena_id = await _seed_trainer_with_arena(db_session)
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    past = date.today() - timedelta(days=3)
    target = past + timedelta(days=7)
    # Block target window: slot exists and is booked by another client
    tg2 = unique_test_telegram_id()
    phone2, phone_n2 = belarus_test_phone(tg2)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'O', 'T', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg2, "phone": phone2, "pn": phone_n2},
    )
    (other_client_id,) = r.fetchone()
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked', :aid)
            RETURNING id
        """),
        {"tid": trainer_id, "d": target, "aid": arena_id},
    )
    (block_slot_id,) = r.fetchone()
    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
        """),
        {"sid": block_slot_id, "tid": trainer_id, "cid": other_client_id, "svc": service_id},
    )
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked', :aid)
            RETURNING id
        """),
        {"tid": trainer_id, "d": past, "aid": arena_id},
    )
    (orig_slot_id,) = r.fetchone()
    r = await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            RETURNING id
        """),
        {"sid": orig_slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    out = await trainer_repeat_booking_same_time_next_week(db_session, booking_id, trainer_id)
    assert out.get("success") is False
    assert out.get("error") == "slot_booked"
