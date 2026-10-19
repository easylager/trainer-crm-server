"""TASK-292: migration 0241 ice_company_core upgrade/downgrade."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0241_ice_company_core.py"


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


@pytest.mark.asyncio
async def test_ice_company_core_columns_roundtrip(db_session) -> None:
    await _run_migration_step(db_session, "downgrade")
    cols = (
        await db_session.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'ice_companies'
                ORDER BY ordinal_position
                """
            )
        )
    ).scalars().all()
    assert "min_people" in cols

    await _run_migration_step(db_session, "upgrade")
    cols = (
        await db_session.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'ice_companies'
                ORDER BY ordinal_position
                """
            )
        )
    ).scalars().all()
    assert "min_people" not in cols
    assert "status" in cols
    reminders = (
        await db_session.execute(
            text(
                """
                SELECT to_regclass('public.ice_company_reminders')
                """
            )
        )
    ).scalar()
    assert reminders is None
