"""Replace cohort schedule, cancel group slots, upcoming list."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id

from src.application.training_group_use_cases import (
    TrainingGroupReplaceBlockedError,
    cancel_future_group_slots_in_range,
    cancel_group_slot,
    create_training_group,
    has_future_group_slots_with_bookings,
    list_upcoming_group_slots,
    replace_training_group_schedule,
)


async def _minimal_trainer_with_service(session: AsyncSession) -> tuple[int, int]:
    service_id = await require_seed_service_id(session)
    r = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'T', 30)"
        ),
        {"tid": trainer_id},
    )
    await session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await session.commit()
    return int(trainer_id), int(service_id)


def _next_weekday(d: date, weekday: int) -> date:
    delta = (weekday - d.weekday()) % 7
    return d + timedelta(days=delta)


@pytest.mark.asyncio
async def test_replace_schedule_changes_rules_and_slots(db_session: AsyncSession) -> None:
    trainer_id, service_id = await _minimal_trainer_with_service(db_session)
    d0 = _next_weekday(date.today() + timedelta(days=1), 1)
    gid = await create_training_group(
        db_session,
        trainer_id,
        name="R1",
        service_id=service_id,
        arena_id=None,
        max_members=8,
        status="recruiting",
        season_start_date=None,
        catalog_visible=False,
        catalog_pitch=None,
        schedule_rules=[{"day_of_week": d0.weekday(), "start_time": "10:00", "duration_minutes": 60}],
    )
    d1 = _next_weekday(date.today() + timedelta(days=1), 2)
    if d1.weekday() == d0.weekday():
        d1 = d1 + timedelta(days=7)
    await replace_training_group_schedule(
        db_session,
        trainer_id,
        gid,
        schedule_rules=[{"day_of_week": d1.weekday(), "start_time": "11:00", "duration_minutes": 60}],
    )
    r = await db_session.execute(
        text(
            """
            SELECT COUNT(*)::int FROM training_group_schedule_rules
            WHERE training_group_id = :gid AND day_of_week = :dow AND start_time = '11:00:00'
            """
        ),
        {"gid": gid, "dow": d1.weekday()},
    )
    assert int(r.scalar() or 0) >= 1


@pytest.mark.asyncio
async def test_replace_blocked_when_booking_on_future_group_slot(db_session: AsyncSession) -> None:
    trainer_id, service_id = await _minimal_trainer_with_service(db_session)
    d = _next_weekday(date.today() + timedelta(days=3), 3)
    gid = await create_training_group(
        db_session,
        trainer_id,
        name="R2",
        service_id=service_id,
        arena_id=None,
        max_members=8,
        status="recruiting",
        season_start_date=None,
        catalog_visible=False,
        catalog_pitch=None,
        schedule_rules=[{"day_of_week": d.weekday(), "start_time": "14:00", "duration_minutes": 60}],
    )
    r = await db_session.execute(
        text(
            """
            SELECT id FROM slots
            WHERE trainer_id = :tid AND training_group_id = :gid AND slot_date = :d
              AND start_time = '14:00:00' AND status != 'cancelled'
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "gid": gid, "d": d},
    )
    row = r.fetchone()
    assert row is not None
    slot_id = int(row[0])
    r2 = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:tid, 'C') RETURNING id"),
        {"tid": unique_test_telegram_id()},
    )
    (client_id,) = r2.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": int(client_id), "svc": service_id},
    )
    await db_session.commit()

    assert await has_future_group_slots_with_bookings(db_session, trainer_id, gid) is True

    with pytest.raises(TrainingGroupReplaceBlockedError):
        await replace_training_group_schedule(
            db_session,
            trainer_id,
            gid,
            schedule_rules=[{"day_of_week": (d.weekday() + 1) % 7, "start_time": "09:00", "duration_minutes": 60}],
        )


@pytest.mark.asyncio
async def test_cancel_group_slot_and_range(db_session: AsyncSession) -> None:
    trainer_id, service_id = await _minimal_trainer_with_service(db_session)
    d = _next_weekday(date.today() + timedelta(days=2), 4)
    gid = await create_training_group(
        db_session,
        trainer_id,
        name="R3",
        service_id=service_id,
        arena_id=None,
        max_members=8,
        status="recruiting",
        season_start_date=None,
        catalog_visible=False,
        catalog_pitch=None,
        schedule_rules=[{"day_of_week": d.weekday(), "start_time": "16:00", "duration_minutes": 60}],
    )
    upcoming = await list_upcoming_group_slots(db_session, trainer_id, gid, limit=5)
    assert len(upcoming) >= 1
    sid = upcoming[0]["id"]
    ok = await cancel_group_slot(db_session, trainer_id, gid, sid)
    assert ok is True
    n = await cancel_future_group_slots_in_range(db_session, trainer_id, gid, date.today(), date.today() + timedelta(days=400))
    assert n >= 0
