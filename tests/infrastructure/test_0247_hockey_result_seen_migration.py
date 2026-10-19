"""TASK-299: migration 0247 hockey_picks.result_seen_at upgrade/downgrade."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0247_hockey_result_seen.py"


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


async def _has_column(db_session) -> bool:
    return (await db_session.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hockey_picks' AND column_name = 'result_seen_at'
                """))).first() is not None


@pytest.mark.asyncio
async def test_result_seen_column_roundtrip(db_session) -> None:
    assert await _has_column(db_session)
    await _run_migration_step(db_session, "downgrade")
    assert not await _has_column(db_session)
    await _run_migration_step(db_session, "upgrade")
    assert await _has_column(db_session)
