"""TASK-221: welcome trial clock starts on first real completed booking."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    create_booking,
    mark_booking_completed_and_notify,
)
from src.application.subscription_tier_use_cases import (
    get_trainer_entitlements,
    get_trainer_subscription_status,
)
from src.application.subscription_use_cases import (
    TRIAL_CLOCK_PENDING_EXPIRES_AT,
    create_trial_subscription,
    ensure_trainer_welcome_trial,
    maybe_start_trial_clock_on_completed_booking,
    resolve_trial_period_days,
)
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


async def _trainer_with_slot(session: AsyncSession) -> tuple[int, int, int]:
    service_id = await require_seed_service_id(session)
    r = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Trial', 'Clock', 30)"
        ),
        {"tid": trainer_id},
    )
    await session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) "
            "VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    tomorrow = date.today() + timedelta(days=1)
    r = await session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, :start, :end, 'available', 1)
            RETURNING id
        """),
        {
            "tid": trainer_id,
            "d": tomorrow,
            "start": time(10, 0),
            "end": time(11, 0),
        },
    )
    (slot_id,) = r.fetchone()
    await session.commit()
    return trainer_id, slot_id, service_id


async def _client(session: AsyncSession) -> int:
    tg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(tg)
    r = await session.execute(
        text("""
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn)
            RETURNING id
        """),
        {"tg": tg, "phone": phone, "pn": phone_normalized},
    )
    (client_id,) = r.fetchone()
    await session.commit()
    return client_id


async def _trial_row(session: AsyncSession, trainer_id: int) -> tuple:
    r = await session.execute(
        text("""
            SELECT ts.expires_at, ts.trial_clock_started_at, ts.status
            FROM trainer_subscriptions ts
            JOIN subscription_plans sp ON sp.id = ts.plan_id
            WHERE ts.trainer_id = :tid AND sp.is_trial = true
            ORDER BY ts.id DESC
            LIMIT 1
        """),
        {"tid": trainer_id},
    )
    return r.fetchone()


@pytest.mark.asyncio
async def test_create_trial_is_pending_clock(db_session: AsyncSession) -> None:
    trainer_id, _, _ = await _trainer_with_slot(db_session)
    created = await create_trial_subscription(db_session, trainer_id)
    assert created is not None
    assert created.get("trial_clock_started") is False

    row = await _trial_row(db_session, trainer_id)
    assert row is not None
    expires_at, clock_at, status = row
    assert status == "trial"
    assert clock_at is None
    assert expires_at.replace(tzinfo=timezone.utc) == TRIAL_CLOCK_PENDING_EXPIRES_AT

    ent = await get_trainer_entitlements(db_session, trainer_id)
    assert ent.has_base_crm is True
    assert ent.modules.get("online") is True
    assert ent.modules.get("analytics") is True
    assert ent.modules.get("groups") is True

    st = await get_trainer_subscription_status(db_session, trainer_id)
    assert st["is_trial"] is True
    assert st["trial_clock_started"] is False
    assert st["expires_at"] is None
    assert st["is_active"] is True


@pytest.mark.asyncio
async def test_ensure_welcome_trial_pending_and_paid_skip(db_session: AsyncSession) -> None:
    trainer_id, _, _ = await _trainer_with_slot(db_session)
    await ensure_trainer_welcome_trial(db_session, trainer_id)
    row = await _trial_row(db_session, trainer_id)
    assert row is not None and row[1] is None

    # Second ensure does not start the clock.
    await ensure_trainer_welcome_trial(db_session, trainer_id)
    row2 = await _trial_row(db_session, trainer_id)
    assert row2 is not None and row2[1] is None


@pytest.mark.asyncio
async def test_first_real_completed_starts_clock(db_session: AsyncSession) -> None:
    trainer_id, slot_id, service_id = await _trainer_with_slot(db_session)
    await create_trial_subscription(db_session, trainer_id)
    client_id = await _client(db_session)

    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert booking_id is not None
    await db_session.execute(
        text("UPDATE bookings SET status = 'confirmed' WHERE id = :bid"),
        {"bid": booking_id},
    )
    await db_session.commit()

    before = datetime.now(timezone.utc)
    await mark_booking_completed_and_notify(db_session, booking_id)
    after = datetime.now(timezone.utc)

    row = await _trial_row(db_session, trainer_id)
    assert row is not None
    expires_at, clock_at, _ = row
    assert clock_at is not None
    plan_days = await resolve_trial_period_days(db_session, 14)
    # expires ≈ now + N days (allow a few seconds skew)
    expected_low = before + timedelta(days=plan_days) - timedelta(seconds=5)
    expected_high = after + timedelta(days=plan_days) + timedelta(seconds=5)
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    assert expected_low <= exp <= expected_high

    st = await get_trainer_subscription_status(db_session, trainer_id)
    assert st["trial_clock_started"] is True
    assert st["expires_at"] is not None


@pytest.mark.asyncio
async def test_sandbox_completed_does_not_start_clock(db_session: AsyncSession) -> None:
    trainer_id, slot_id, service_id = await _trainer_with_slot(db_session)
    await create_trial_subscription(db_session, trainer_id)
    client_id = await _client(db_session)

    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
        is_sandbox=True,
    )
    assert booking_id is not None
    await db_session.execute(
        text("UPDATE bookings SET status = 'completed', is_sandbox = true WHERE id = :bid"),
        {"bid": booking_id},
    )
    await db_session.commit()

    started = await maybe_start_trial_clock_on_completed_booking(db_session, booking_id)
    await db_session.commit()
    assert started is False
    row = await _trial_row(db_session, trainer_id)
    assert row is not None and row[1] is None


@pytest.mark.asyncio
async def test_second_completed_does_not_extend_trial(db_session: AsyncSession) -> None:
    trainer_id, slot_id, service_id = await _trainer_with_slot(db_session)
    await create_trial_subscription(db_session, trainer_id)
    client_id = await _client(db_session)

    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert booking_id is not None
    await db_session.execute(
        text("UPDATE bookings SET status = 'completed' WHERE id = :bid"),
        {"bid": booking_id},
    )
    await db_session.commit()
    assert await maybe_start_trial_clock_on_completed_booking(db_session, booking_id) is True
    await db_session.commit()
    row1 = await _trial_row(db_session, trainer_id)
    assert row1 is not None
    expires1 = row1[0]

    # Second completed (same booking re-call or another) must not move expires_at.
    assert await maybe_start_trial_clock_on_completed_booking(db_session, booking_id) is False
    await db_session.commit()
    row2 = await _trial_row(db_session, trainer_id)
    assert row2 is not None
    assert row2[0] == expires1
