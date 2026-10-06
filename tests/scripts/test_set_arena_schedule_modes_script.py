"""TASK-204: set_arena_schedule_modes.py dry-run does not write."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from scripts import set_arena_schedule_modes as script
from tests.api.test_public_arenas import _insert_arena, _insert_city


@pytest.mark.asyncio
async def test_dry_run_does_not_change_profile(app_use_test_db, db_session, monkeypatch) -> None:
    cid = await _insert_city(db_session, name=f"Script-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Скриптовый каток")
    monkeypatch.setattr(
        script,
        "SPECS",
        (script.ArenaModeSpec(arena_id, script.SCHEDULE_MODE_PHONE),),
    )
    await db_session.commit()

    before = (
        await db_session.execute(
            text("SELECT schedule_mode FROM arena_profiles WHERE arena_id = :id"),
            {"id": arena_id},
        )
    ).scalar_one()
    assert before == "auto"

    lines = await script.plan_updates(db_session)
    assert any(f"#{arena_id}" in line and "-> phone" in line for line in lines)

    after = (
        await db_session.execute(
            text("SELECT schedule_mode FROM arena_profiles WHERE arena_id = :id"),
            {"id": arena_id},
        )
    ).scalar_one()
    assert after == "auto"
