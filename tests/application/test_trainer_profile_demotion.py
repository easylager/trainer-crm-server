"""Active trainer is demoted to pending_profile when profile becomes incomplete."""
import pytest
from sqlalchemy import text

from src.application.trainer_use_cases import (
    create_trainer,
    get_trainer,
    update_trainer_profile,
    update_trainer_status,
)
from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_active_demoted_when_first_name_cleared(db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r2.scalar()
    r3 = await db_session.execute(text("SELECT id FROM arenas ORDER BY id LIMIT 1"))
    aid = r3.scalar()
    if sid is None or cid is None or aid is None:
        pytest.skip("need seed services, cities, and arenas")

    tid = await create_trainer(
        db_session,
        profile={
            "first_name": "Иван",
            "last_name": "Петров",
            "age": 25,
            "phone": "+375291112233",
            "contacts": "@ivan",
            "description": "x" * 30,
            "city_id": cid,
            "education": "Высшее профильное",
            "experience_years": 3,
            "session_duration_minutes": 45,
            "min_hours_before_booking": 24,
        },
        service_ids=[sid],
        arena_ids=[aid],
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_photos (trainer_id, file_key, sort_order) "
            "VALUES (:tid, :fk, 0)"
        ),
        {"tid": tid, "fk": "trainers/1/test.jpg"},
    )
    await db_session.commit()

    await update_trainer_status(db_session, tid, TRAINER_STATUS_ACTIVE)
    await update_trainer_profile(db_session, tid, profile={"first_name": ""})

    row = await get_trainer(db_session, tid)
    assert row is not None
    assert row["status"] == "pending_profile"
    assert (row.get("profile") or {}).get("first_name") == ""
