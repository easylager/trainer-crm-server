"""Admin post-hoc moderation queue for trainer-created arenas (TASK-046 AC-007)."""

import pytest
from sqlalchemy import text

from src.application.admin_arena_moderation import (
    approve_arena,
    list_arenas_pending_moderation,
    reject_arena,
)
from src.application.trainer_arena_create_use_cases import create_trainer_arena
from src.application.trainer_use_cases import create_trainer


async def _trainer_with_arena(db_session, *, monkeypatch) -> tuple[int, int, int]:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r2.scalar()
    if sid is None or cid is None:
        pytest.skip("need seed services and cities")

    async def _fake_geocode(address, city_name):
        return None

    monkeypatch.setattr(
        "src.application.trainer_arena_create_use_cases._geocode_address",
        _fake_geocode,
    )

    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Ivan", "last_name": "Pending", "phone": "+375291119911", "city_id": cid},
        service_ids=[sid],
        arena_ids=[],
    )
    result = await create_trainer_arena(
        db_session, trainer_id, name="Арена на модерации", address="ул. Модераторская, 1"
    )
    assert result["status"] == "created"
    return trainer_id, cid, result["arena_id"]


@pytest.mark.asyncio
async def test_list_arenas_pending_moderation_includes_new_unconfirmed_arena(
    db_session, monkeypatch
) -> None:
    trainer_id, _, arena_id = await _trainer_with_arena(db_session, monkeypatch=monkeypatch)
    pending = await list_arenas_pending_moderation(db_session)
    ids = [p["id"] for p in pending]
    assert arena_id in ids
    row = next(p for p in pending if p["id"] == arena_id)
    assert row["trainer_id"] == trainer_id


@pytest.mark.asyncio
async def test_approve_arena_marks_confirmed_and_leaves_moderation_queue(db_session, monkeypatch) -> None:
    _, _, arena_id = await _trainer_with_arena(db_session, monkeypatch=monkeypatch)
    ok = await approve_arena(db_session, arena_id, admin_id=999)
    assert ok is True

    row = (
        await db_session.execute(
            text("SELECT is_confirmed, confirmed_by_admin_id FROM arenas WHERE id = :id"),
            {"id": arena_id},
        )
    ).fetchone()
    assert row[0] is True
    assert row[1] == 999

    pending = await list_arenas_pending_moderation(db_session)
    assert arena_id not in [p["id"] for p in pending]


@pytest.mark.asyncio
async def test_reject_arena_deactivates_even_when_already_selected_by_another_trainer(
    db_session, monkeypatch
) -> None:
    """AC-007: reject deactivates unconditionally, even if another trainer already uses it."""
    _, city_id, arena_id = await _trainer_with_arena(db_session, monkeypatch=monkeypatch)

    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    other_trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Other", "last_name": "User", "phone": "+375291119922", "city_id": city_id},
        service_ids=[sid],
        arena_ids=[arena_id],
    )

    ok = await reject_arena(db_session, arena_id)
    assert ok is True

    row = (
        await db_session.execute(text("SELECT is_active FROM arenas WHERE id = :id"), {"id": arena_id})
    ).fetchone()
    assert row[0] is False

    # The other trainer's link row is untouched by design (EDGE-003) — just the arena itself
    # is deactivated, so it drops out of any is_active-filtered listing for both trainers.
    link = (
        await db_session.execute(
            text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
            {"tid": other_trainer_id, "aid": arena_id},
        )
    ).fetchone()
    assert link is not None
