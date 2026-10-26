"""TASK-335: migration 0271 — ×2 на ходе, напоминания у игрока, журнал сообщений."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"


async def _step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / "0271_hockey_double_and_reminders.py"))
    assert migration["down_revision"] == "0270_hockey_races"
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            migration[step]()

    await connection.run_sync(invoke)


@pytest.mark.asyncio
async def test_double_remind_notices_roundtrip(db_session) -> None:
    await db_session.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (880271001, 'Саша')"))
    await db_session.execute(text("INSERT INTO hockey_player_prefs (player_key) VALUES (880271001)"))
    assert (
        await db_session.execute(text("SELECT remind FROM hockey_player_prefs WHERE player_key = 880271001"))
    ).scalar_one() is False
    match_id = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', 'mig271', 'Динамо-Минск', 'Барыс', now()) RETURNING id
                """)
        )
    ).scalar_one()
    notice = text("INSERT INTO hockey_notices (player_key, match_id, kind) VALUES (880271001, :m, :k)")
    await db_session.execute(notice, {"m": match_id, "k": "before"})
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(notice, {"m": match_id, "k": "weird"})
    await _step(db_session, "downgrade")
    assert (await db_session.execute(text("SELECT to_regclass('hockey_notices')"))).scalar_one() is None
    await _step(db_session, "upgrade")
    assert (await db_session.execute(text("SELECT to_regclass('hockey_notices')"))).scalar_one() is not None
