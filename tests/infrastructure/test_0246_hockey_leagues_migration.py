"""TASK-298: migration 0246 hockey_leagues / hockey_league_members upgrade/downgrade."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0246_hockey_leagues.py"


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


async def _tables(db_session) -> list[str]:
    return (await db_session.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name IN ('hockey_leagues', 'hockey_league_members') ORDER BY table_name
            """))).scalars().all()


@pytest.mark.asyncio
async def test_hockey_leagues_roundtrip_and_guards(db_session) -> None:
    await _run_migration_step(db_session, "downgrade")
    assert await _tables(db_session) == []
    await _run_migration_step(db_session, "upgrade")
    assert await _tables(db_session) == ["hockey_league_members", "hockey_leagues"]

    await db_session.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (7, 'Саша')"))
    await db_session.execute(
        text("INSERT INTO hockey_leagues (name, owner_key, invite_code) VALUES ('ОХМ', 7, 'ABCDEFGH')")
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("INSERT INTO hockey_leagues (name, owner_key, invite_code) VALUES ('Ещё', 7, 'ABCDEFGH')")
            )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("INSERT INTO hockey_leagues (name, owner_key, invite_code) VALUES ('   ', 7, 'ZZZZZZZZ')")
            )
