"""
PRD E7 T7.1: matrix-style integration tests — payment class × preset × slot timing (before/after end).

Covers representative rows; expand when CERT / reconciliation paths gain dedicated fixtures.
"""
from __future__ import annotations

from datetime import date, timedelta, time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_problem_use_cases import submit_trainer_booking_problem
from src.application.booking_use_cases import (
    BOOKING_STATUS_NO_SHOW,
    BOOKING_STATUS_PAYMENT_DISPUTE,
)

from tests.conftest import unique_test_telegram_id
from tests.integration.test_booking_use_cases import _create_client, _create_trainer_and_slot


@pytest.mark.parametrize(
    ("preset", "expect_status", "expect_bl"),
    [
        ("A1", BOOKING_STATUS_NO_SHOW, False),
        ("A2", BOOKING_STATUS_PAYMENT_DISPUTE, True),
    ],
)
@pytest.mark.asyncio
async def test_qa_matrix_none_branch_status_and_blacklist_flag(
    db_session: AsyncSession,
    preset: str,
    expect_status: str,
    expect_bl: bool,
) -> None:
    """NONE payment class: A1 → no_show / A2 → payment_dispute + blacklist_candidate."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0), status="booked"
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    err, _msg = await submit_trainer_booking_problem(
        db_session, booking_id, trainer_id, preset, None, "qa_matrix"
    )
    assert err is None
    r2 = await db_session.execute(text("SELECT status FROM bookings WHERE id = :id"), {"id": booking_id})
    assert (r2.scalar() or "").strip() == expect_status
    r3 = await db_session.execute(
        text("SELECT blacklist_candidate FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert bool(r3.scalar()) is expect_bl


@pytest.mark.asyncio
async def test_qa_matrix_submit_ok_when_slot_in_past_or_future(db_session: AsyncSession) -> None:
    """Late reporting (past end) and in-window booking: both must accept NONE/A1 (T7.1 timing)."""
    yesterday = date.today() - timedelta(days=1)
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_past, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(9, 0), time(10, 0), status="booked"
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow, "st": time(14, 0), "et": time(15, 0)},
    )
    (slot_future,) = r.fetchone()
    cid1 = await _create_client(db_session, unique_test_telegram_id())
    cid2 = await _create_client(db_session, unique_test_telegram_id())
    bids: list[int] = []
    for slot_id, cid in ((slot_past, cid1), (slot_future, cid2)):
        rb = await db_session.execute(
            text(
                """
                INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
                VALUES (:sid, :tid, :cid, :svc, 'confirmed')
                RETURNING id
                """
            ),
            {"sid": slot_id, "tid": trainer_id, "cid": cid, "svc": service_id},
        )
        bids.append(int(rb.fetchone()[0]))
    await db_session.commit()

    for bid in bids:
        err, _m = await submit_trainer_booking_problem(
            db_session, bid, trainer_id, "A1", None, "qa_matrix"
        )
        assert err is None
        rs = await db_session.execute(text("SELECT status FROM bookings WHERE id = :id"), {"id": bid})
        assert (rs.scalar() or "").strip() == BOOKING_STATUS_NO_SHOW


@pytest.mark.asyncio
async def test_qa_matrix_one_off_a1(db_session: AsyncSession) -> None:
    """ONE_OFF: positive booking_price_cents without pass/cert → presets A1/A2."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(12, 0), time(13, 0), status="booked"
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, booking_price_cents)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed', 5000)
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    err, _msg = await submit_trainer_booking_problem(
        db_session, booking_id, trainer_id, "A1", None, "qa_matrix"
    )
    assert err is None
    rs = await db_session.execute(
        text("SELECT payment_class FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert (rs.scalar() or "").strip() == "ONE_OFF"


@pytest.mark.asyncio
async def test_a1_absence_only_does_not_set_problematic(db_session: AsyncSession) -> None:
    """A1 + client_action absence_only: report row, no problematic flag on client."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(16, 0), time(17, 0), status="booked"
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    err, _msg = await submit_trainer_booking_problem(
        db_session,
        booking_id,
        trainer_id,
        "A1",
        None,
        "qa_matrix",
        client_action="absence_only",
    )
    assert err is None
    rp = await db_session.execute(
        text("SELECT problematic FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    assert rp.scalar() is False
    rbl = await db_session.execute(
        text("SELECT blacklist_candidate FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert rbl.scalar() is False


@pytest.mark.asyncio
async def test_a1_blacklist_sets_candidate_and_problematic(db_session: AsyncSession) -> None:
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(17, 0), time(18, 0), status="booked"
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    err, _msg = await submit_trainer_booking_problem(
        db_session,
        booking_id,
        trainer_id,
        "A1",
        None,
        "qa_matrix",
        client_action="blacklist",
    )
    assert err is None
    rp = await db_session.execute(
        text("SELECT problematic FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    assert rp.scalar() is True
    rbl = await db_session.execute(
        text("SELECT blacklist_candidate FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert rbl.scalar() is True


@pytest.mark.asyncio
async def test_client_action_not_allowed_for_a2(db_session: AsyncSession) -> None:
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(18, 0), time(19, 0), status="booked"
    )
    client_id = await _create_client(db_session, unique_test_telegram_id())
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    err, _msg = await submit_trainer_booking_problem(
        db_session,
        booking_id,
        trainer_id,
        "A2",
        None,
        "qa_matrix",
        client_action="attention",
    )
    assert err == "bad_request"
