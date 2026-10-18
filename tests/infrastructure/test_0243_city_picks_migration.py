"""Миграция 0243 city_picks: upgrade и downgrade."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0243_city_picks.py"


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


@pytest.mark.asyncio
async def test_city_picks_migration_roundtrip(db_session) -> None:
    await _run_migration_step(db_session, "downgrade")
    gone = (
        await db_session.execute(text("SELECT to_regclass('public.city_picks')"))
    ).scalar_one()
    assert gone is None

    await _run_migration_step(db_session, "upgrade")
    cols = (
        await db_session.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'city_picks'
                ORDER BY ordinal_position
                """
            )
        )
    ).scalars().all()
    assert cols == ["city_id", "position", "arena_id", "updated_at"]
