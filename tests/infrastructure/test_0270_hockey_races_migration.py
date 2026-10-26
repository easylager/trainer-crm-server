"""TASK-334: migration 0270 hockey_races / hockey_crowns / hockey_race_seen / hockey_leagues.club."""

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
    migration = runpy.run_path(str(MIGRATIONS / "0270_hockey_races.py"))
    assert migration["revision"] == "0270_hockey_races"
    assert migration["down_revision"] == "0269_ice_watch_delivery"
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            migration[step]()

    await connection.run_sync(invoke)


async def _exists(db_session, name: str) -> bool:
    return (await db_session.execute(text("SELECT to_regclass(:n)"), {"n": name})).scalar_one() is not None


@pytest.mark.asyncio
async def test_races_crowns_unique_and_roundtrip(db_session) -> None:
    race_id = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_races (club, title, starts_at, ends_at)
                VALUES ('Динамо-Минск', 'ноябрь', '2026-10-31 21:00+00', '2026-11-30 21:00+00') RETURNING id
                """)
        )
    ).scalar_one()
    await db_session.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (880270001, 'Саша')"))
    crown = text("INSERT INTO hockey_crowns (race_id, player_key, points, exact) VALUES (:r, 880270001, 50, 1)")
    await db_session.execute(crown, {"r": race_id})
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(crown, {"r": race_id})
    league = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_leagues (name, owner_key, invite_code) VALUES ('ОХМ', 880270001, 'MIG27001')
                RETURNING club
                """)
        )
    ).scalar_one()
    assert league == "Динамо-Минск"
    await db_session.execute(text("INSERT INTO hockey_card_events (kind, card) VALUES ('shared', 'crown')"))
    await _step(db_session, "downgrade")
    assert not await _exists(db_session, "hockey_races")
    await _step(db_session, "upgrade")
    assert await _exists(db_session, "hockey_crowns") and await _exists(db_session, "hockey_race_seen")
