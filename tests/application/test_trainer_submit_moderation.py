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
    # Since 0182_catalog_opt_in the queue is entered only on the trainer's own request; a
    # complete profile alone must never publish them (see test below).
    await db_session.execute(
        text("UPDATE trainers SET is_catalog_visible = true WHERE id = :tid"), {"tid": tid}
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


@pytest.mark.asyncio
async def test_submit_moderation_refuses_until_trainer_asks_for_catalog(db_session, monkeypatch) -> None:
    """
    A complete profile is not a request to be published.

    The Mini App auto-submits after every save, so without this gate a trainer who polished
    their card for their own students was queued for the public catalog and listed on approval
    — never having been asked. The refusal is a noop, not an error: nothing is wrong.
    """
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
            "first_name": "Анна",
            "last_name": "Сидорова",
            "age": 31,
            "phone": "+375291112244",
            "description": "y" * 30,
            "city_id": cid,
            "education": "higher",
            "experience_years": 5,
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

    res = await try_submit_trainer_for_moderation_review(db_session, tid)
    assert res["ok"] is True
    assert res["noop"] is True
    assert res["reason"] == "catalog_opt_out"
    assert notified == []
    r = await db_session.execute(
        text("SELECT moderation_submitted_at FROM trainers WHERE id = :tid"), {"tid": tid}
    )
    assert r.scalar() is None

    # Turning the switch on is the request — the same call then queues normally.
    await db_session.execute(
        text("UPDATE trainers SET is_catalog_visible = true WHERE id = :tid"), {"tid": tid}
    )
    await db_session.commit()
    assert await try_submit_trainer_for_moderation_review(db_session, tid) == {
        "ok": True,
        "submitted": True,
    }
    assert notified == [tid]


@pytest.mark.asyncio
async def test_onboarding_checklist_heals_stuck_catalog_queue(db_session, monkeypatch) -> None:
    """
    Opt-in + complete profile + never stamped → checklist GET queues and notifies.

    Reproduces the hub bug: carousel finished without submit-for-moderation, admin bot silent,
    toggle still on. Opening the hub (checklist) must heal once.
    """
    from src.application.trainer_onboarding_checklist import get_trainer_onboarding_checklist

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
            "first_name": "Кира",
            "last_name": "Лёд",
            "age": 28,
            "phone": "+375291118877",
            "description": "w" * 30,
            "city_id": cid,
            "education": "higher",
            "experience_years": 4,
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
        {"tid": tid, "fk": "trainers/1/heal.jpg"},
    )
    await db_session.execute(
        text(
            "UPDATE trainers SET is_catalog_visible = true, moderation_submitted_at = NULL "
            "WHERE id = :tid"
        ),
        {"tid": tid},
    )
    await db_session.commit()

    notified: list[int] = []

    async def fake_notify(trainer_id: int) -> None:
        notified.append(trainer_id)

    monkeypatch.setattr(
        "src.application.trainer_use_cases.notify_admins_trainer_queued_for_moderation",
        fake_notify,
    )

    data = await get_trainer_onboarding_checklist(db_session, tid)
    assert data is not None
    assert data["moderation_submitted"] is True
    assert notified == [tid]

    # Second checklist load must not re-notify.
    data2 = await get_trainer_onboarding_checklist(db_session, tid)
    assert data2 is not None
    assert data2["moderation_submitted"] is True
    assert notified == [tid]
