"""Очки FIFA: migration 0250 — ограничение 0/10/20/30/50 и сброс старых очков."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0250_hockey_fifa_points.py"


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


@pytest.mark.asyncio
async def test_fifa_points_constraint_roundtrip(db_session) -> None:
    async def ok(points: int) -> bool:
        try:
            async with db_session.begin_nested():
                await db_session.execute(
                    text("UPDATE hockey_picks SET points = :p WHERE id = (SELECT min(id) FROM hockey_picks)"),
                    {"p": points},
                )
            return True
        except IntegrityError:
            return False

    await db_session.execute(
        text("INSERT INTO hockey_players (player_key, display_name) VALUES (880250001, 'Т') ON CONFLICT DO NOTHING")
    )
    mid = (
        await db_session.execute(
            text(
                "INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status) "
                "VALUES ('hcdinamo', 'm0250', 'Динамо-Минск', 'Барыс', now(), 'scheduled') RETURNING id"
            )
        )
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO hockey_picks (match_id, player_key, side) VALUES (:m, 880250001, 'home')"), {"m": mid}
    )
    assert all([await ok(p) for p in (0, 10, 20, 30, 50)])
    assert not await ok(5) and not await ok(40)
    await _run_migration_step(db_session, "downgrade")
    assert await ok(5) and not await ok(50)
    await _run_migration_step(db_session, "upgrade")
    assert await ok(30)
