"""TASK-196 AC-1: миграция 0221 заполняет arena_profiles.timezone по стране города.

Колонка существовала и раньше, но была NULL у всех арен — и весь продукт молча
жил на «все города UTC+3». Миграция наполняет её из города: BY → Europe/Minsk,
RU → Europe/Moscow; вручную выставленную таймзону не трогает.
"""
from __future__ import annotations

import pathlib
import runpy
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from src.application.arena_profile import ensure_arena_profile

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0221_arena_timezone_backfill.py"


async def _insert_arena_with_profile(db_session, *, country: str, timezone: str | None = None) -> int:
    """Арена с профилем в городе с заданной страной; таймзона профиля — как передали."""
    ins_city = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group, is_active)
            VALUES (:name, :c, :pg, true)
            RETURNING id
            """
        ),
        {
            "name": f"TzCity-{country}-{uuid.uuid4().hex[:6]}",
            "c": country,
            "pg": "BY_BASE" if country == "BY" else "RU_BASE",
        },
    )
    cid = int(ins_city.scalar_one())
    arena_name = f"Арена {uuid.uuid4().hex[:8]}"
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'ул. Ледовая, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": cid, "name": arena_name},
    )
    arena_id = int(ins.scalar_one())
    await ensure_arena_profile(db_session, arena_id, city_id=cid, name=arena_name)
    if timezone is not None:
        await db_session.execute(
            text("UPDATE arena_profiles SET timezone = :tz WHERE arena_id = :aid"),
            {"tz": timezone, "aid": arena_id},
        )
    await db_session.flush()
    return arena_id


async def _arena_timezone(db_session, arena_id: int) -> str | None:
    return await db_session.scalar(
        text("SELECT timezone FROM arena_profiles WHERE arena_id = :aid"),
        {"aid": arena_id},
    )


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


@pytest.mark.asyncio
async def test_backfill_fills_timezone_by_city_country(app_use_test_db, db_session) -> None:
    by_arena = await _insert_arena_with_profile(db_session, country="BY")
    ru_arena = await _insert_arena_with_profile(db_session, country="RU")
    manual_arena = await _insert_arena_with_profile(db_session, country="RU", timezone="Asia/Yekaterinburg")

    await _run_migration_step(db_session, "upgrade")

    assert await _arena_timezone(db_session, by_arena) == "Europe/Minsk"
    assert await _arena_timezone(db_session, ru_arena) == "Europe/Moscow"
    # Ручная таймзона не затирается бэкфиллом.
    assert await _arena_timezone(db_session, manual_arena) == "Asia/Yekaterinburg"

    # Повторный upgrade идемпотентен: ручное значение остаётся ручным.
    await _run_migration_step(db_session, "upgrade")
    assert await _arena_timezone(db_session, manual_arena) == "Asia/Yekaterinburg"


@pytest.mark.asyncio
async def test_backfill_downgrade_returns_timezone_to_null(app_use_test_db, db_session) -> None:
    by_arena = await _insert_arena_with_profile(db_session, country="BY")
    ru_arena = await _insert_arena_with_profile(db_session, country="RU")

    await _run_migration_step(db_session, "upgrade")
    await _run_migration_step(db_session, "downgrade")

    assert await _arena_timezone(db_session, by_arena) is None
    assert await _arena_timezone(db_session, ru_arena) is None
