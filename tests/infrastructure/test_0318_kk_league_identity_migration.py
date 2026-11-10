"""TASK-361: миграция 0317 — картинка и «на что играем» у лиги, таблица жалоб: вверх и вниз."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0318_kk_league_identity.py"


async def _run(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


async def _league_columns(db_session) -> set[str]:
    rows = await db_session.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = 'hockey_leagues'")
    )
    return set(rows.scalars().all())


async def _has_reports_table(db_session) -> bool:
    found = await db_session.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name = 'hockey_league_reports'")
    )
    return found.first() is not None


async def _league(db_session, code: str) -> int:
    await db_session.execute(
        text("INSERT INTO hockey_players (player_key, display_name) VALUES (361, 'Саша') ON CONFLICT DO NOTHING")
    )
    return int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO hockey_leagues (name, owner_key, invite_code, starts_at, ends_at)
                    VALUES ('ОХМ', 361, :code, now(), now() + interval '30 days') RETURNING id
                    """),
                {"code": code},
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_roundtrip_keeps_existing_leagues(db_session) -> None:
    assert {"image_key", "stake_text"} <= await _league_columns(db_session)
    assert await _has_reports_table(db_session)

    await _run(db_session, "downgrade")
    assert not ({"image_key", "stake_text"} & await _league_columns(db_session))
    assert not await _has_reports_table(db_session)

    league_id = await _league(db_session, "OLDLEAGU")  # лига, созданная до миграции
    await _run(db_session, "upgrade")
    assert {"image_key", "stake_text"} <= await _league_columns(db_session)
    row = (
        await db_session.execute(text("SELECT name, image_key, stake_text FROM hockey_leagues WHERE id = :i"), {"i": league_id})
    ).one()
    assert (row.name, row.image_key, row.stake_text) == ("ОХМ", None, None)


@pytest.mark.asyncio
async def test_stake_text_guard_and_report_cascade(db_session) -> None:
    league_id = await _league(db_session, "STAKELEA")
    await db_session.execute(
        text("UPDATE hockey_leagues SET stake_text = 'Кофе', image_key = 'kk-leagues/1/a.jpg' WHERE id = :i"), {"i": league_id}
    )
    for bad in ("   ", "", "я" * 81):
        with pytest.raises((IntegrityError, Exception)):  # noqa: B017 — CHECK либо длина столбца
            async with db_session.begin_nested():
                await db_session.execute(
                    text("UPDATE hockey_leagues SET stake_text = :s WHERE id = :i"), {"s": bad, "i": league_id}
                )

    await db_session.execute(
        text("INSERT INTO hockey_league_reports (league_id, reporter_key) VALUES (:i, 5), (:i, 6)"), {"i": league_id}
    )
    stamped = (
        await db_session.execute(text("SELECT created_at, alerted_at FROM hockey_league_reports WHERE reporter_key = 5"))
    ).one()
    assert stamped.created_at is not None and stamped.alerted_at is None
    await db_session.execute(text("DELETE FROM hockey_leagues WHERE id = :i"), {"i": league_id})
    left = (await db_session.execute(text("SELECT COUNT(*) FROM hockey_league_reports WHERE league_id = :i"), {"i": league_id})).scalar_one()
    assert left == 0  # лига ушла — жалобы на неё тоже

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text("INSERT INTO hockey_league_reports (league_id, reporter_key) VALUES (999999999, 1)"))
