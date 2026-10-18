"""TASK-297: migration 0245 hockey_players / hockey_picks upgrade/downgrade и защита хода."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0245_hockey_picks.py"
DEPENDENT_FILE = "0246_hockey_leagues.py"


async def _run_migration_step(db_session, step: str, file: str = MIGRATION_FILE) -> None:
    migration = runpy.run_path(str(MIGRATIONS / file))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


async def _tables(db_session) -> list[str]:
    return (await db_session.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name IN ('hockey_players', 'hockey_picks') ORDER BY table_name
            """))).scalars().all()


@pytest.mark.asyncio
async def test_hockey_picks_roundtrip_and_score_side_guard(db_session) -> None:
    # Лиги (0246) ссылаются на игроков — снимаем первыми, возвращаем в конце.
    await _run_migration_step(db_session, "downgrade", DEPENDENT_FILE)
    await _run_migration_step(db_session, "downgrade")
    assert await _tables(db_session) == []
    await _run_migration_step(db_session, "upgrade")
    assert await _tables(db_session) == ["hockey_picks", "hockey_players"]

    match_id = (await db_session.execute(text("""
            INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
            VALUES ('hcdinamo', 'mig', 'Динамо-Минск', 'Барыс', now()) RETURNING id
            """))).scalar_one()
    await db_session.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (1, 'Саша')"))
    # Счёт 1:4 при ставке «за хозяев» противоречит сам себе — база такой ход не примет.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("""
                    INSERT INTO hockey_picks (match_id, player_key, side, home_score, away_score)
                    VALUES (:m, 1, 'home', 1, 4)
                    """),
                {"m": match_id},
            )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO hockey_picks (match_id, player_key, side, home_score, away_score) VALUES (:m, 1, 'home', 2, 2)"
                ),
                {"m": match_id},
            )

    await _run_migration_step(db_session, "upgrade", DEPENDENT_FILE)
