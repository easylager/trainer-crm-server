"""Removing a service from trainer profile is blocked while slots / bookings / templates / groups reference it."""
import pytest
from sqlalchemy import text

from src.application.trainer_use_cases import (
    create_trainer,
    ensure_trainer_services_replace_allowed,
    update_trainer_profile,
)


@pytest.mark.asyncio
async def test_cannot_remove_service_referenced_by_slot(db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 2"))
    rows = r.fetchall()
    if len(rows) < 2:
        pytest.skip("need at least 2 services")
    s1, s2 = int(rows[0][0]), int(rows[1][0])
    r2 = await db_session.execute(text("SELECT id FROM arenas ORDER BY id LIMIT 1"))
    aid = r2.scalar()
    if aid is None:
        pytest.skip("need arena")

    tid = await create_trainer(
        db_session,
        profile={"first_name": "A", "last_name": "B", "age": 30},
        service_ids=[s1, s2],
        arena_ids=[aid],
    )
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, '10:00:00', '11:00:00', 'available', 2, :sid)
            """
        ),
        {"tid": tid, "d": "2030-01-15", "sid": s1},
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="слот"):
        await ensure_trainer_services_replace_allowed(db_session, tid, {s2})

    await ensure_trainer_services_replace_allowed(db_session, tid, {s1})


@pytest.mark.asyncio
async def test_update_trainer_profile_raises_when_removing_used_service(db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 2"))
    rows = r.fetchall()
    if len(rows) < 2:
        pytest.skip("need at least 2 services")
    s1, s2 = int(rows[0][0]), int(rows[1][0])
    r2 = await db_session.execute(text("SELECT id FROM arenas ORDER BY id LIMIT 1"))
    aid = r2.scalar()
    if aid is None:
        pytest.skip("need arena")

    tid = await create_trainer(
        db_session,
        profile={"first_name": "C", "last_name": "D", "age": 28},
        service_ids=[s1, s2],
        arena_ids=[aid],
    )
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, '12:00:00', '13:00:00', 'available', 2, :sid)
            """
        ),
        {"tid": tid, "d": "2030-02-01", "sid": s1},
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="слот"):
        await update_trainer_profile(db_session, tid, service_ids=[s2])
