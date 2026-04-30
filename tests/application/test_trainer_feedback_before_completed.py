"""Trainer «Оставить отзыв» from wrap-up works while booking is still confirmed/pending."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import (
    get_booking_for_trainer_feedback,
    set_booking_trainer_review,
)

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


async def _seed_trainer_client_booking(db_session, *, booking_status: str) -> tuple[int, int, int]:
    """trainer_id, booking_id, client_telegram_id."""
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'T', 'R', 30, :cid)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"
        ),
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
    d = date.today() + timedelta(days=1)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked', :aid)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": d, "aid": arena_id},
    )
    (slot_id,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, :st)
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id, "st": booking_status},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()
    return trainer_id, booking_id, tg


@pytest.mark.asyncio
async def test_trainer_feedback_allowed_for_confirmed_booking(db_session) -> None:
    trainer_id, booking_id, _ = await _seed_trainer_client_booking(db_session, booking_status="confirmed")
    got = await get_booking_for_trainer_feedback(db_session, booking_id, trainer_id)
    assert got == {"id": booking_id}
    ok = await set_booking_trainer_review(db_session, booking_id, trainer_id, "Хорошая работа")
    assert ok is True
    r = await db_session.execute(
        text("SELECT trainer_review_text FROM bookings WHERE id = :id"),
        {"id": booking_id},
    )
    row = r.fetchone()
    assert row and row[0] == "Хорошая работа"


@pytest.mark.asyncio
async def test_trainer_feedback_disallowed_for_cancelled(db_session) -> None:
    trainer_id, booking_id, _ = await _seed_trainer_client_booking(db_session, booking_status="cancelled")
    assert await get_booking_for_trainer_feedback(db_session, booking_id, trainer_id) is None
    assert await set_booking_trainer_review(db_session, booking_id, trainer_id, "x") is False
