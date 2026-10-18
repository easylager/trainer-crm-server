"""TASK-294: migration 0242 client broadcasts upgrade/downgrade."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0242_client_broadcasts.py"


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


@pytest.mark.asyncio
async def test_client_broadcasts_migration_roundtrip(db_session) -> None:
    await _run_migration_step(db_session, "downgrade")
    for table in ("client_broadcast_log", "client_broadcast_optouts"):
        cols = (
            await db_session.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = :table
                    """
                ),
                {"table": table},
            )
        ).all()
        assert cols == []

    await _run_migration_step(db_session, "upgrade")
    log_cols = (
        await db_session.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'client_broadcast_log'
                ORDER BY ordinal_position
                """
            )
        )
    ).scalars().all()
    assert log_cols == ["id", "telegram_id", "campaign_key", "sent_at", "status", "error"]
    opt_cols = (
        await db_session.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'client_broadcast_optouts'
                ORDER BY ordinal_position
                """
            )
        )
    ).scalars().all()
    assert opt_cols == ["telegram_id", "kind", "created_at"]

    await db_session.execute(
        text(
            """
            INSERT INTO client_broadcast_log (telegram_id, campaign_key, status)
            VALUES (4242, 'season_start_2026', 'sent')
            """
        )
    )
    await db_session.execute(
        text(
            """
            INSERT INTO client_broadcast_optouts (telegram_id, kind)
            VALUES (4242, 'ice_forecast')
            """
        )
    )
    await db_session.flush()
