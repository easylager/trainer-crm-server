"""Миграция 0244: характеры минских катков, upgrade и downgrade."""

from __future__ import annotations

import pathlib
import runpy
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from src.application.arena_profile import backfill_arena_profiles

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"


async def _step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / "0244_minsk_load_characters.py"))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            migration[step]()

    await connection.run_sync(invoke)


async def _rink(db_session, city_id: int, slug: str, character: str = "steady") -> int:
    aid = int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO arenas (city_id, name, address, is_active, is_confirmed) "
                    "VALUES (:c, :n, 'ул. Ледовая, 1', true, true) RETURNING id"
                ),
                {"c": city_id, "n": f"Каток-{uuid.uuid4().hex[:6]}"},
            )
        ).scalar_one()
    )
    await backfill_arena_profiles(db_session)
    await db_session.execute(
        text("UPDATE arena_profiles SET slug = :s, load_character = :ch WHERE arena_id = :a"),
        {"s": slug, "ch": character, "a": aid},
    )
    return aid


async def _character(db_session, aid: int) -> str:
    return str(
        (await db_session.execute(text("SELECT load_character FROM arena_profiles WHERE arena_id = :a"), {"a": aid})).scalar_one()
    )


@pytest.mark.asyncio
async def test_minsk_characters_roundtrip_and_admin_edit_kept(db_session) -> None:
    minsk = (
        await db_session.execute(text("SELECT id FROM cities WHERE country = 'BY' AND name = 'Минск' ORDER BY id LIMIT 1"))
    ).scalar_one_or_none()
    if minsk is None:
        pytest.skip("в тестовой БД нет Минска")
    await db_session.execute(
        text("DELETE FROM arena_profiles WHERE city_id = :c AND slug IN ('chizhovka', 'minsk-junost', 'ledby')"),
        {"c": minsk},
    )
    chizh = await _rink(db_session, int(minsk), "chizhovka")
    junost = await _rink(db_session, int(minsk), "minsk-junost")
    edited = await _rink(db_session, int(minsk), "ledby", character="quiet")  # правка админа

    await _step(db_session, "upgrade")
    assert await _character(db_session, chizh) == "hot"
    assert await _character(db_session, junost) == "quiet"
    assert await _character(db_session, edited) == "quiet"

    await _step(db_session, "downgrade")
    assert await _character(db_session, chizh) == "steady"
    assert await _character(db_session, junost) == "steady"
