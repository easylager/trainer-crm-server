"""Trainer stats revenue must follow booking_price_cents after retroactive edits."""

from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.stats_use_cases import _trainer_calendar_revenue_total

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


@pytest.mark.asyncio
async def test_stats_session_revenue_uses_booking_price_snapshot(
    db_session: AsyncSession,
) -> None:
    service_id = await require_seed_service_id(db_session)
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'T', 'T', 30, :cid)
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
    slot_day = date.today() - timedelta(days=2)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, '10:00', '11:00', 'booked', :aid)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_day, "aid": arena_id},
    )
    (slot_id,) = r_slot.fetchone()
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r_cl = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'C', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r_cl.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (
                slot_id, trainer_id, client_id, service_id, status, booking_price_cents
            )
            VALUES (:sid, :tid, :cid, :svc, 'completed', 7500)
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    total = await _trainer_calendar_revenue_total(db_session, trainer_id, slot_day, slot_day)
    assert total == 7500
