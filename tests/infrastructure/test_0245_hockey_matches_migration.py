"""TASK-296: migration 0245 hockey_matches upgrade/downgrade и защита итога."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0245_hockey_matches.py"
DEPENDENT_FILES = ("0247_hockey_leagues.py", "0246_hockey_picks.py")


async def _run_migration_step(db_session, step: str, file: str = MIGRATION_FILE) -> None:
    migration = runpy.run_path(str(MIGRATIONS / file))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


async def _columns(db_session) -> list[str]:
    return (await db_session.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'hockey_matches' ORDER BY ordinal_position
            """))).scalars().all()


@pytest.mark.asyncio
async def test_hockey_matches_roundtrip_and_final_guard(db_session) -> None:
    # Ходы и лиги (0245, 0246) ссылаются на матчи — их снимаем первыми и возвращаем в конце.
    for dependent in DEPENDENT_FILES:
        await _run_migration_step(db_session, "downgrade", dependent)
    await _run_migration_step(db_session, "downgrade")
    assert await _columns(db_session) == []

    await _run_migration_step(db_session, "upgrade")
    cols = await _columns(db_session)
    assert cols[:6] == ["id", "source", "source_match_id", "home_team", "away_team", "starts_at"]
    assert "decided_in" in cols and "review_alerted_at" in cols

    await db_session.execute(text("""
        INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
        VALUES ('hcdinamo', '1', 'Динамо-Минск', 'Барыс', now())
        """))
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            # «Окончен» без счёта не бывает: защищает игру от очков по пустому итогу.
            await db_session.execute(text("UPDATE hockey_matches SET status = 'final' WHERE source_match_id = '1'"))
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text("""
                UPDATE hockey_matches SET status = 'final', home_score = 2, away_score = 2,
                    decided_in = 'regulation', result_source = 'auto' WHERE source_match_id = '1'
                """))

    for dependent in reversed(DEPENDENT_FILES):
        await _run_migration_step(db_session, "upgrade", dependent)
