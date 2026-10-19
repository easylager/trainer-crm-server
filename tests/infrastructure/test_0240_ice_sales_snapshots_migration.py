"""TASK-295: migration 0240 ice_sales_snapshots upgrade/downgrade."""

from __future__ import annotations

import pathlib
import runpy
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
MIGRATION_FILE = "0240_ice_sales_snapshots.py"


async def _run_migration_step(db_session, step: str) -> None:
    migration = runpy.run_path(str(MIGRATIONS / MIGRATION_FILE))
    connection = await db_session.connection()

    def invoke(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration[step]()

    await connection.run_sync(invoke)


@pytest.mark.asyncio
async def test_ice_sales_snapshots_table_roundtrip(db_session) -> None:
    await _run_migration_step(db_session, "downgrade")
    cols = (await db_session.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'ice_sales_snapshots'
                """))).all()
    assert cols == []

    await _run_migration_step(db_session, "upgrade")
    cols = (await db_session.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'ice_sales_snapshots'
                ORDER BY ordinal_position
                """))).scalars().all()
    assert cols == [
        "id",
        "arena_id",
        "local_date",
        "starts_at_local",
        "observed_at",
        "capacity",
        "sold",
        "held",
        "source",
    ]

    city_id = int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO cities (name, country, price_group, is_active)
                    VALUES (:name, 'BY', 'BY_BASE', true)
                    RETURNING id
                    """),
                {"name": f"SnapCity-{uuid.uuid4().hex[:6]}"},
            )
        ).scalar_one()
    )
    arena_id = int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, 'Arena', 'addr', true, true)
                    RETURNING id
                    """),
                {"cid": city_id},
            )
        ).scalar_one()
    )
    await db_session.execute(
        text("""
            INSERT INTO ice_sales_snapshots (
                arena_id, local_date, starts_at_local, observed_at,
                capacity, sold, held, source
            )
            VALUES (
                :aid, '2026-10-04', '13:15', '2026-10-04T09:00:00+03:00',
                115, 40, 5, 'korona'
            )
            """),
        {"aid": arena_id},
    )
    await db_session.flush()
