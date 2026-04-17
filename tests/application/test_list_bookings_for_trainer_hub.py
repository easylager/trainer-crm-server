"""
Trainer hub list (PRD E1): session visible until slot end; current window sorts first.
Requires test DB (alembic upgrade head).
"""
from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import list_bookings_for_trainer

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


async def _seed_trainer_with_service(db_session) -> tuple[int, int]:
    """trainer_id, service_id."""
    arena_id, city_id, _arena_name = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'Test', 'Trainer', 25, :cid)
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
    return trainer_id, service_id


@pytest.mark.asyncio
async def test_hub_excludes_booking_after_slot_end_today(db_session) -> None:
    """Ended slot on calendar today must not appear (replaces loose slot_date >= today only)."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
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
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, CURRENT_DATE - 1, TIME '10:00', TIME '11:00', 'booked')
            RETURNING id
        """),
        {"tid": trainer_id},
    )
    (slot_id,) = r.fetchone()
    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
        """),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    bookings = await list_bookings_for_trainer(db_session, trainer_id, limit=50)
    assert bookings == []


@pytest.mark.asyncio
async def test_hub_sorts_in_session_booking_before_later_same_day(db_session) -> None:
    """Within [start,end) now is first; later same-day slot follows."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    clients: list[int] = []
    for _ in range(2):
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
        (cid,) = r.fetchone()
        clients.append(cid)

    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date,
                ((CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk') - INTERVAL '45 minutes')::time,
                ((CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk') + INTERVAL '2 hours')::time,
                'booked'
            )
            RETURNING id
        """),
        {"tid": trainer_id},
    )
    (slot_now,) = r.fetchone()

    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date,
                TIME '23:00',
                TIME '23:45',
                'booked'
            )
            RETURNING id
        """),
        {"tid": trainer_id},
    )
    (slot_later,) = r.fetchone()

    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
        """),
        {"sid": slot_later, "tid": trainer_id, "cid": clients[1], "svc": service_id},
    )
    r = await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            RETURNING id
        """),
        {"sid": slot_now, "tid": trainer_id, "cid": clients[0], "svc": service_id},
    )
    (bid_now,) = r.fetchone()
    await db_session.commit()

    bookings = await list_bookings_for_trainer(db_session, trainer_id, limit=50)
    assert len(bookings) == 2
    assert bookings[0]["id"] == bid_now
    assert bookings[0]["hub_in_session"] is True
    assert bookings[1]["hub_in_session"] is False


@pytest.mark.asyncio
async def test_hub_tomorrow_still_listed(db_session) -> None:
    """Future day bookings unchanged."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tomorrow = date.today() + timedelta(days=1)
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
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
        """),
        {"tid": trainer_id, "d": tomorrow, "st": time(10, 0), "et": time(11, 0)},
    )
    (slot_id,) = r.fetchone()
    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
        """),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    bookings = await list_bookings_for_trainer(db_session, trainer_id, limit=50)
    assert len(bookings) == 1
    assert bookings[0]["hub_in_session"] is False
