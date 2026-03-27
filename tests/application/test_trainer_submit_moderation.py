"""Submit-for-moderation use case: idempotency and resubmit after profile edits."""
import pytest
from sqlalchemy import text

from src.application.trainer_use_cases import (
    create_trainer,
    try_submit_trainer_for_moderation_review,
    update_trainer_profile,
)


@pytest.mark.asyncio
async def test_submit_moderation_notifies_once_until_profile_changes(db_session, monkeypatch) -> None:
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
            "education": "higher",
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

    notified: list[int] = []

    async def fake_notify(trainer_id: int) -> None:
        notified.append(trainer_id)

    monkeypatch.setattr(
        "src.application.trainer_use_cases.notify_admins_trainer_queued_for_moderation",
        fake_notify,
    )

    first = await try_submit_trainer_for_moderation_review(db_session, tid)
    assert first == {"ok": True, "submitted": True}
    assert notified == [tid]

    second = await try_submit_trainer_for_moderation_review(db_session, tid)
    assert second["ok"] is True
    assert second["noop"] is True
    assert second["reason"] == "already_submitted"
    assert notified == [tid]

    await update_trainer_profile(db_session, tid, profile={"description": "z" * 30})
    third = await try_submit_trainer_for_moderation_review(db_session, tid)
    assert third == {"ok": True, "submitted": True}
    assert notified == [tid, tid]
