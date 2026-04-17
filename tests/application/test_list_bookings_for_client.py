"""
Client hub / GET /client/bookings: only sessions whose slot end is still in the future (Europe/Minsk).
"""
import pytest
from sqlalchemy import text

from src.application.booking_use_cases import list_bookings_for_client

from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service
from tests.conftest import belarus_test_phone, unique_test_telegram_id


@pytest.mark.asyncio
async def test_client_list_excludes_ended_slots_keeps_future(db_session) -> None:
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

    r_past = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date - 1,
                TIME '10:00',
                TIME '11:00',
                'booked'
            )
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (slot_past,) = r_past.fetchone()

    r_future = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date + 1,
                TIME '10:00',
                TIME '11:00',
                'booked'
            )
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (slot_future,) = r_future.fetchone()

    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_past, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_future, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    rows = await list_bookings_for_client(db_session, tg, limit=50)
    ids = [r["id"] for r in rows]
    assert len(ids) == 1
    r_only = await db_session.execute(
        text("SELECT slot_id FROM bookings WHERE id = :id"),
        {"id": ids[0]},
    )
    assert int(r_only.scalar()) == int(slot_future)
