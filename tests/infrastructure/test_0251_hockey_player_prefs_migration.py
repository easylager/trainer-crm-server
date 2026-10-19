"""TASK-304: migration 0251 hockey_player_prefs upgrade/downgrade."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0251_hockey_player_prefs.py"


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    assert migration["revision"] == "0251_hockey_player_prefs"
    assert migration["down_revision"] == "0250_hockey_fifa_points"
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


async def _has_table(db_session) -> bool:
    return (await db_session.execute(text("SELECT to_regclass('hockey_player_prefs')"))).scalar_one() is not None


@pytest.mark.asyncio
async def test_player_prefs_roundtrip_and_defaults(db_session) -> None:
    assert await _has_table(db_session)
    await db_session.execute(text("INSERT INTO hockey_player_prefs (player_key) VALUES (880251001)"))
    row = (
        await db_session.execute(
            text("SELECT kk_hidden, updated_at FROM hockey_player_prefs WHERE player_key = 880251001")
        )
    ).one()
    assert row.kk_hidden is False and row.updated_at is not None
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text("INSERT INTO hockey_player_prefs (player_key) VALUES (880251001)"))
    await _run_migration_step(db_session, "downgrade")
    assert not await _has_table(db_session)
    await _run_migration_step(db_session, "upgrade")
    assert await _has_table(db_session)
