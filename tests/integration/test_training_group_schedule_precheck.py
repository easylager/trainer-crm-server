"""
Training group creation: schedule conflict checks vs templates, slots, recurring clients.
"""
from datetime import date, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id

from src.application.training_group_use_cases import (
    TrainingGroupScheduleConflictError,
    create_training_group,
    validate_training_group_schedule_before_create,
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
    """Next occurrence of weekday (0=Mon .. 6=Sun) on or after d."""
    delta = (weekday - d.weekday()) % 7
    return d + timedelta(days=delta)


@pytest.mark.asyncio
async def test_precheck_blocks_group_template_row(db_session: AsyncSession) -> None:
    trainer_id, service_id = await _minimal_trainer_with_service(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_schedule_templates
            (trainer_id, day_of_week, start_time, duration_minutes, capacity, service_id)
            VALUES (:tid, 1, '17:00', 60, 3, :sid)
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.commit()

    with pytest.raises(TrainingGroupScheduleConflictError) as ei:
        await validate_training_group_schedule_before_create(
            db_session,
            trainer_id,
            None,
            [{"day_of_week": 1, "start_time": "17:00", "duration_minutes": 60}],
            None,
        )
    assert ei.value.code == "group_template"


@pytest.mark.asyncio
async def test_precheck_blocks_recurring_client(db_session: AsyncSession) -> None:
    trainer_id, service_id = await _minimal_trainer_with_service(db_session)
    r = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:tid, 'C') RETURNING id"),
        {"tid": unique_test_telegram_id()},
    )
    (client_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO recurring_client_slots
            (trainer_id, client_id, day_of_week, start_time, end_time, status)
            VALUES (:tid, :cid, 2, '10:00', '11:00', 'active')
            """
        ),
        {"tid": trainer_id, "cid": int(client_id)},
    )
    await db_session.commit()

    with pytest.raises(TrainingGroupScheduleConflictError) as ei:
        await validate_training_group_schedule_before_create(
            db_session,
            trainer_id,
            None,
            [{"day_of_week": 2, "start_time": "10:00", "duration_minutes": 60}],
            None,
        )
    assert ei.value.code == "recurring"


@pytest.mark.asyncio
async def test_create_group_replaces_empty_slot_and_inserts_group_slots(db_session: AsyncSession) -> None:
    trainer_id, service_id = await _minimal_trainer_with_service(db_session)
    d = _next_weekday(date.today() + timedelta(days=1), 3)
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, '12:00', '13:00', 'available', 1)
            """
        ),
        {"tid": trainer_id, "d": d},
    )
    await db_session.commit()

    gid = await create_training_group(
        db_session,
        trainer_id,
        name="G1",
        service_id=service_id,
        arena_id=None,
        max_members=8,
        status="recruiting",
        season_start_date=None,
        catalog_visible=False,
        catalog_pitch=None,
        schedule_rules=[{"day_of_week": d.weekday(), "start_time": "12:00", "duration_minutes": 60}],
    )
    assert gid > 0

    r = await db_session.execute(
        text(
            """
            SELECT COUNT(*)::int FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND start_time = '12:00'
              AND training_group_id = :gid AND status != 'cancelled'
            """
        ),
        {"tid": trainer_id, "d": d, "gid": gid},
    )
    assert int(r.scalar() or 0) >= 1


@pytest.mark.asyncio
async def test_create_group_blocks_booked_slot(db_session: AsyncSession) -> None:
    trainer_id, service_id = await _minimal_trainer_with_service(db_session)
    d = _next_weekday(date.today() + timedelta(days=2), 4)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, '15:00', '16:00', 'booked', 1)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": d},
    )
    (slot_id,) = r.fetchone()
    r2 = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:tid, 'B') RETURNING id"),
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
        {"sid": int(slot_id), "tid": trainer_id, "cid": int(client_id), "svc": service_id},
    )
    await db_session.commit()

    with pytest.raises(TrainingGroupScheduleConflictError):
        await create_training_group(
            db_session,
            trainer_id,
            name="Gx",
            service_id=service_id,
            arena_id=None,
            max_members=8,
            status="recruiting",
            season_start_date=None,
            catalog_visible=False,
            catalog_pitch=None,
            schedule_rules=[{"day_of_week": d.weekday(), "start_time": "15:00", "duration_minutes": 60}],
        )
