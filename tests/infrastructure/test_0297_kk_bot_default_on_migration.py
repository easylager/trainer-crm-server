"""TASK-334 S6: миграция 0297 меняет только значение по умолчанию — выключенное остаётся выключенным."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
FILE = "0297_kk_bot_default_on.py"


async def _run(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            migration[step]()

    await connection.run_sync(invoke)


async def _remind(db_session, key: int):
    return (
        await db_session.execute(text("SELECT remind FROM hockey_player_prefs WHERE player_key = :k"), {"k": key})
    ).scalar_one()


@pytest.mark.asyncio
async def test_existing_off_stays_off_and_new_rows_default_on(db_session) -> None:
    await _run(db_session, "downgrade")
    for key in (880297001, 880297002):
        await db_session.execute(
            text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'И')"), {"k": key}
        )
    await db_session.execute(text("INSERT INTO hockey_player_prefs (player_key, remind) VALUES (880297001, false)"))
    await db_session.execute(text("INSERT INTO hockey_player_prefs (player_key, remind) VALUES (880297002, true)"))

    await _run(db_session, "upgrade")
    assert await _remind(db_session, 880297001) is False
    assert await _remind(db_session, 880297002) is True

    await db_session.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (880297003, 'Н')"))
    await db_session.execute(text("INSERT INTO hockey_player_prefs (player_key) VALUES (880297003)"))
    assert await _remind(db_session, 880297003) is True
