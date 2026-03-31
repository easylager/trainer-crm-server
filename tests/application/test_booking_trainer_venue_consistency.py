"""
Venue label for schedule slots must match booking detail arenas_str (same SQL + normalization).
Requires test DB (alembic upgrade head).
"""
from datetime import date, timedelta, time

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import (
    active_booking_summaries_by_slot_for_trainer_range,
    list_bookings_for_trainer,
)

from tests.conftest import belarus_test_phone, unique_test_telegram_id


@pytest.mark.asyncio
async def test_venue_label_matches_booking_arenas_str(db_session) -> None:
    """One booking: schedule summary venue_label == list_bookings_for_trainer arenas_str."""
    tomorrow = date.today() + timedelta(days=1)
    r = await db_session.execute(text("INSERT INTO cities (name, sort_order) VALUES ('T', 0) RETURNING id"))
    (city_id,) = r.fetchone()
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'R', 25)"
        ),
        {"tid": trainer_id},
    )
    r = await db_session.execute(
        text("INSERT INTO services (name, sort_order) VALUES ('Svc', 0) RETURNING id")
    )
    (service_id,) = r.fetchone()
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, sort_order)
            VALUES (:cid, 'Ice Park Alpha', 0) RETURNING id
            """
        ),
        {"cid": city_id},
    )
    (arena_id,) = r.fetchone()
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
        """),
        {"tid": trainer_id, "d": tomorrow, "st": time(10, 0), "et": time(11, 0)},
    )
    (slot_id,) = r.fetchone()
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text("""
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn)
            RETURNING id
        """),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
        """),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    bookings = await list_bookings_for_trainer(db_session, trainer_id)
    assert len(bookings) == 1
    arenas_str = bookings[0]["arenas_str"]

    summaries = await active_booking_summaries_by_slot_for_trainer_range(
        db_session, trainer_id, tomorrow, tomorrow
    )
    assert slot_id in summaries
    venue_label = summaries[slot_id]["venue_label"]

    assert venue_label == arenas_str == "Ice Park Alpha"
