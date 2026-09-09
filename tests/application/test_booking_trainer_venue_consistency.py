"""
Venue label for schedule slots must match booking detail arenas_str (same SQL + normalization).
Requires test DB (alembic upgrade head).
"""
from datetime import date, timedelta, time

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import (
    BOOKING_ARENA_UNSPECIFIED_LABEL,
    active_booking_summaries_by_slot_for_trainer_range,
    list_bookings_for_trainer,
)

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


@pytest.mark.asyncio
async def test_venue_label_matches_booking_arenas_str(db_session) -> None:
    """TASK-056: no booking/slot arena → same placeholder on hub list and schedule summary."""
    tomorrow = date.today() + timedelta(days=1)
    arena_id, city_id, _arena_name = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
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
    assert summaries[slot_id].get("booking_service_id") == service_id
    assert summaries[slot_id].get("client_id") == client_id
    assert summaries[slot_id].get("client_telegram_id") == tg
    assert summaries[slot_id].get("client_phone") == phone

    assert venue_label == arenas_str == BOOKING_ARENA_UNSPECIFIED_LABEL
