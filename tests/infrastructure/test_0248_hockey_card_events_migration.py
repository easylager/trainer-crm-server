"""TASK-300: migration 0248 hockey_card_events upgrade/downgrade."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0248_hockey_card_events.py"


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


async def _has_table(db_session) -> bool:
    return (await db_session.execute(text("SELECT to_regclass('hockey_card_events')"))).scalar_one() is not None


@pytest.mark.asyncio
async def test_card_events_roundtrip_and_checks(db_session) -> None:
    assert await _has_table(db_session)
    await db_session.execute(text("INSERT INTO hockey_card_events (kind, card) VALUES ('shared', 'result')"))
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text("INSERT INTO hockey_card_events (kind, card) VALUES ('liked', 'result')"))
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text("INSERT INTO hockey_card_events (kind, card) VALUES ('shared', 'match')"))
    await _run_migration_step(db_session, "downgrade")
    assert not await _has_table(db_session)
    await _run_migration_step(db_session, "upgrade")
    assert await _has_table(db_session)
