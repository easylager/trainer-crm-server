"""TASK-204 AC-1: migration 0222 arena schedule_mode columns and check."""
from __future__ import annotations

import pathlib
import runpy
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from src.application.arena_profile import ensure_arena_profile

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0222_arena_schedule_mode.py"


async def _insert_arena(db_session) -> int:
    ins_city = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group, is_active)
            VALUES (:name, 'BY', 'BY_BASE', true)
            RETURNING id
            """
        ),
        {"name": f"ModeCity-{uuid.uuid4().hex[:6]}"},
    )
    cid = int(ins_city.scalar_one())
    name = f"Арена {uuid.uuid4().hex[:8]}"
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'ул. Ледовая, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": cid, "name": name},
    )
    arena_id = int(ins.scalar_one())
    await ensure_arena_profile(db_session, arena_id, city_id=cid, name=name)
    await db_session.flush()
    return arena_id


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


@pytest.mark.asyncio
async def test_schedule_mode_defaults_and_roundtrip(app_use_test_db, db_session) -> None:
    """DB fixture is already at head; exercise downgrade → upgrade on 0222."""
    arena_id = await _insert_arena(db_session)
    row = (
        await db_session.execute(
            text(
                """
                SELECT schedule_mode, reopen_date, schedule_mode_note
                FROM arena_profiles WHERE arena_id = :id
                """
            ),
            {"id": arena_id},
        )
    ).one()
    assert row == ("auto", None, None)

    await _run_migration_step(db_session, "downgrade")
    cols = (
        await db_session.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'arena_profiles' AND column_name = 'schedule_mode'
                """
            )
        )
    ).fetchall()
    assert cols == []

    await _run_migration_step(db_session, "upgrade")
    row2 = (
        await db_session.execute(
            text("SELECT schedule_mode FROM arena_profiles WHERE arena_id = :id"),
            {"id": arena_id},
        )
    ).scalar_one()
    assert row2 == "auto"
