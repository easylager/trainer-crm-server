"""TASK-334: миграции 0292/0293 — легаси-данные переезжают без потерь (L10), обратный ход чист."""

from __future__ import annotations

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"


async def _run(db_session, file: str, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / file))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            migration[step]()

    await connection.run_sync(invoke)


@pytest.mark.asyncio
async def test_legacy_data_survives_the_winter_model(db_session) -> None:
    await _run(db_session, "0293_kk_league_terms.py", "downgrade")
    await _run(db_session, "0292_kk_slices_crowns.py", "downgrade")

    await db_session.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (880292001, 'Саша')"))
    match_id = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', 'mig292', 'Динамо-Минск', 'Барыс', '2026-11-17 16:00+00') RETURNING id
                """)
        )
    ).scalar_one()
    await db_session.execute(
        text("""
            INSERT INTO hockey_picks (match_id, player_key, side, doubled)
            VALUES (:m, 880292001, 'home', true)
            """),
        {"m": match_id},
    )
    league_id = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_leagues (name, owner_key, invite_code, created_at)
                VALUES ('ОХМ', 880292001, 'MIG29201', '2026-10-25 10:00+00') RETURNING id
                """)
        )
    ).scalar_one()
    race_id = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_races (club, title, starts_at, ends_at, closed_at)
                VALUES ('Динамо-Минск', 'ноябрь', '2026-10-31 21:00+00', '2026-11-30 21:00+00', now()) RETURNING id
                """)
        )
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO hockey_crowns (race_id, player_key, points, exact) VALUES (:r, 880292001, 50, 1)"),
        {"r": race_id},
    )

    await _run(db_session, "0292_kk_slices_crowns.py", "upgrade")
    await _run(db_session, "0293_kk_league_terms.py", "upgrade")

    pick = (await db_session.execute(text("SELECT doubled, trump_week FROM hockey_picks"))).one()
    assert pick.doubled and pick.trump_week.isoformat() == "2026-11-16"  # неделя пн-вс по Минску
    league = (
        await db_session.execute(
            text("SELECT scope, term_kind, starts_at, ends_at FROM hockey_leagues WHERE id = :l"), {"l": league_id}
        )
    ).one()
    # «Динамо-Минск, до конца сезона»: сезон 2026/27 — с 1 августа 2026 по 1 августа 2027 по Минску.
    assert (league.scope, league.term_kind) == ("dinamo", "season")
    assert league.starts_at.isoformat().startswith("2026-07-31T21:00")
    assert league.ends_at.isoformat().startswith("2027-07-31T21:00")
    crown = (await db_session.execute(text("SELECT club, kind, period_start FROM hockey_crowns"))).one()
    assert (crown.club, crown.kind) == ("Динамо-Минск", "month")
    closure = (await db_session.execute(text("SELECT kind, club FROM hockey_closures"))).one()
    assert (closure.kind, closure.club) == ("month", "Динамо-Минск")
    assert (await db_session.execute(text("SELECT club FROM hockey_races"))).scalar_one() is None

