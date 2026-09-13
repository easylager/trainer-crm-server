"""Submit-for-moderation use case: idempotency and resubmit after profile edits."""
import pytest
from sqlalchemy import text

from src.application.trainer_use_cases import (
    create_trainer,
    set_trainer_catalog_visibility,
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
async def test_resending_unchanged_profile_field_does_not_reset_submission(
    db_session, monkeypatch
) -> None:
    """
    The catalog carousel PATCHes once per step (name, phone, photo, services, arenas...).
    Resending a value that already matches what is stored — or patching a field outside the
    moderation criteria (e.g. schedule_grid_step_minutes) — must not clear
    moderation_submitted_at. It used to clear on *any* PATCH regardless of an actual value
    change, so the next carousel step always saw "not submitted yet" and re-queued + re-notified
    admins once per step of a single edit session.
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
            "first_name": "Олег",
            "last_name": "Кузнецов",
            "age": 27,
            "phone": "+375291112255",
            "description": "q" * 30,
            "city_id": cid,
            "education": "higher",
            "experience_years": 2,
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

    # Re-save the same first_name value — a later carousel step re-saving the whole form.
    await update_trainer_profile(db_session, tid, profile={"first_name": "Олег"})
    again = await try_submit_trainer_for_moderation_review(db_session, tid)
    assert again["ok"] is True
    assert again["noop"] is True
    assert again["reason"] == "already_submitted"
    assert notified == [tid]

    # A field outside the moderation criteria (arena's own schedule step) must not reset it either.
    await update_trainer_profile(
        db_session, tid, profile={}, primary_arena_id_set=True, primary_arena_id=aid
    )
    still = await try_submit_trainer_for_moderation_review(db_session, tid)
    assert still["ok"] is True
    assert still["noop"] is True
    assert still["reason"] == "already_submitted"
    assert notified == [tid]


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
async def test_onboarding_checklist_never_auto_submits(db_session, monkeypatch) -> None:
    """
    Opt-in + complete profile + never stamped → checklist GET must NOT queue or notify.

    This used to "heal" the stuck state by submitting on read. But the same unstamped-looking
    shape also occurs whenever a moderator has left feedback (moderation_submitted flips back to
    False once feedback is non-empty — see moderation_readiness_dict), so a trainer merely
    reopening the app or tapping a hub hint re-queued their card and silently wiped the
    moderator's comment (the reported "sent to moderation ~10 times" bug). Reading status must
    stay free of side effects; only an explicit submit action (toggle-on, carousel finish) may
    queue moderation — see test_trainer_onboarding_catalog_step / test_hub_catalog flows for
    where that explicit submit now lives.
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
    assert data["moderation_submitted"] is False
    assert notified == []

    # Re-reading changes nothing either — no delayed/second-read heal.
    data2 = await get_trainer_onboarding_checklist(db_session, tid)
    assert data2 is not None
    assert data2["moderation_submitted"] is False
    assert notified == []

    r_check = await db_session.execute(
        text("SELECT moderation_submitted_at FROM trainers WHERE id = :tid"), {"tid": tid}
    )
    assert r_check.scalar() is None


@pytest.mark.asyncio
async def test_onboarding_checklist_does_not_clear_moderator_feedback(db_session, monkeypatch) -> None:
    """
    Trainer already submitted once; moderator asked for changes (moderation_feedback set).

    Opening the app / tapping a hub hint after that must show "needs revision" without
    silently clearing the feedback or re-queuing/re-notifying — that resubmission is now an
    explicit trainer action (edit + save), not a side effect of reading status.
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
            "first_name": "Дарья",
            "last_name": "Морозова",
            "age": 26,
            "phone": "+375291118899",
            "description": "v" * 30,
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
        {"tid": tid, "fk": "trainers/1/revision.jpg"},
    )
    await db_session.execute(
        text(
            "UPDATE trainers SET is_catalog_visible = true, moderation_submitted_at = now(), "
            "moderation_feedback = 'Добавьте фото получше' WHERE id = :tid"
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
    assert data["moderation_submitted"] is False
    assert data["catalog_needs_revision"] is True
    assert data["moderation_feedback"] == "Добавьте фото получше"
    assert notified == []

    r_fb = await db_session.execute(
        text("SELECT moderation_feedback FROM trainers WHERE id = :tid"), {"tid": tid}
    )
    assert r_fb.scalar() == "Добавьте фото получше"


@pytest.mark.asyncio
async def test_opt_out_then_opt_in_resubmits_instead_of_silent_noop(db_session, monkeypatch) -> None:
    """
    Opting out must withdraw the queue stamp, so a later opt-in is a fresh request — not a
    silent "already_submitted" noop with no new admin notification. Before this fix, the
    stamp survived opting out, so re-opting in looked like a no-op to the trainer even though
    admin's /pending had already (correctly) dropped them while opted out.
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
            "first_name": "Передумал",
            "last_name": "Обратно",
            "phone": "+375291116677",
            "description": "p" * 30,
            "city_id": cid,
            "education": "higher",
            "experience_years": 2,
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

    assert await set_trainer_catalog_visibility(db_session, tid, visible=True) is True
    first = await try_submit_trainer_for_moderation_review(db_session, tid)
    assert first == {"ok": True, "submitted": True}
    assert notified == [tid]

    # Opts out before admin gets to it.
    assert await set_trainer_catalog_visibility(db_session, tid, visible=False) is True
    r_after_out = await db_session.execute(
        text("SELECT moderation_submitted_at FROM trainers WHERE id = :tid"), {"tid": tid}
    )
    assert r_after_out.scalar() is None

    # Opts back in — must be a genuine fresh request, not a silent "already_submitted" noop.
    assert await set_trainer_catalog_visibility(db_session, tid, visible=True) is True
    second = await try_submit_trainer_for_moderation_review(db_session, tid)
    assert second == {"ok": True, "submitted": True}
    assert notified == [tid, tid]
