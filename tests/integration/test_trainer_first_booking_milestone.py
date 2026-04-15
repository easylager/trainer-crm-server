"""First confirmed booking milestone flags on trainer_profiles (one-time)."""

from datetime import date, timedelta, time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import cancel_booking, create_booking
from tests.integration.test_booking_use_cases import _create_client, _create_trainer_and_slot
from tests.conftest import unique_test_telegram_id


@pytest.mark.asyncio
async def test_first_trainer_booking_claims_milestone_once(db_session: AsyncSession) -> None:
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    bid, flags = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert bid is not None
    assert flags[0] is True and flags[1] is True

    r = await db_session.execute(
        text(
            "SELECT first_booking_milestone_at, share_catalog_tip_sent_at FROM trainer_profiles WHERE trainer_id = :tid"
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    assert row and row[0] is not None and row[1] is not None

    r2 = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, :st, :en, 'available', 1)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow, "st": time(14, 0), "en": time(15, 0)},
    )
    (slot2,) = r2.fetchone()
    await db_session.commit()
    client2 = await _create_client(db_session, unique_test_telegram_id())
    bid2, flags2 = await create_booking(
        db_session,
        slot_id=slot2,
        trainer_id=trainer_id,
        client_id=client2,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert bid2 is not None
    assert flags2 == (False, False)


@pytest.mark.asyncio
async def test_milestone_not_reclaimed_after_cancel_first_booking(db_session: AsyncSession) -> None:
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    bid, flags = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert bid is not None
    assert flags[0] is True

    ok = await cancel_booking(db_session, bid, trainer_id)
    assert ok is True

    r2 = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, :st, :en, 'available', 1)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow, "st": time(16, 0), "en": time(17, 0)},
    )
    (slot2,) = r2.fetchone()
    await db_session.commit()
    client2 = await _create_client(db_session, unique_test_telegram_id())
    _, flags2 = await create_booking(
        db_session,
        slot_id=slot2,
        trainer_id=trainer_id,
        client_id=client2,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert flags2 == (False, False)
