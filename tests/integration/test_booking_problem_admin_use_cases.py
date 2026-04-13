"""PRD E6: admin listing of booking_problem_reports."""
from __future__ import annotations

from datetime import date, timedelta, time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_problem_admin_use_cases import (
    count_booking_problem_reports_for_admin,
    list_booking_problem_reports_for_admin,
)

from tests.conftest import unique_test_telegram_id
from tests.integration.test_booking_use_cases import _create_client, _create_trainer_and_slot


@pytest.mark.asyncio
async def test_list_and_count_booking_problem_reports_admin_filters(db_session: AsyncSession) -> None:
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session,
        yesterday,
        time(9, 0),
        time(10, 0),
        status="booked",
        capacity=2,
    )
    c1 = await _create_client(db_session, unique_test_telegram_id())
    c2 = await _create_client(db_session, unique_test_telegram_id())
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'no_show')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": c1, "svc": service_id},
    )
    (bid_a,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'payment_dispute')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": c2, "svc": service_id},
    )
    (bid_b,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO booking_problem_reports
              (booking_id, trainer_id, client_id, preset_id, payment_class, source, blacklist_candidate)
            VALUES (:bid, :tid, :cid, 'A1', 'NONE', 'test', false)
            """
        ),
        {"bid": bid_a, "tid": trainer_id, "cid": c1},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO booking_problem_reports
              (booking_id, trainer_id, client_id, preset_id, payment_class, source, blacklist_candidate)
            VALUES (:bid, :tid, :cid, 'A2', 'NONE', 'test', true)
            """
        ),
        {"bid": bid_b, "tid": trainer_id, "cid": c2},
    )
    await db_session.commit()

    n_all = await count_booking_problem_reports_for_admin(db_session, blacklist_only=False)
    n_bl = await count_booking_problem_reports_for_admin(db_session, blacklist_only=True)
    assert n_all >= 2
    assert n_bl >= 1

    only_bl = await list_booking_problem_reports_for_admin(
        db_session, limit=50, offset=0, blacklist_only=True
    )
    bl_ids = {x["booking_id"] for x in only_bl}
    assert bid_b in bl_ids
    assert bid_a not in bl_ids
