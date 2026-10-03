"""Downgrades must not discard append-only client share history."""

import pathlib
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text


MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"


@pytest.mark.parametrize(
    ("migration_file", "kind"),
    [
        ("0208_shops_place_shares.py", "place"),
        ("0210_catalog_entry_clicks.py", "selection"),
    ],
)
@pytest.mark.asyncio
async def test_downgrade_refuses_to_discard_new_kind_history(db_session, migration_file, kind) -> None:
    await db_session.execute(text("ALTER TABLE client_share_events DROP CONSTRAINT ck_client_share_events_kind"))
    await db_session.execute(
        text(
            "ALTER TABLE client_share_events ADD CONSTRAINT ck_client_share_events_kind "
            "CHECK (kind IN ('ice_city_day', 'trainer', 'place', 'selection'))"
        )
    )
    # This test database may be on a different branch's migration head. Supply the
    # objects and compatible data needed to exercise each downgrade's own guard.
    await db_session.execute(text("UPDATE arenas SET venue_type = 'other'"))
    await db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS catalog_entry_clicks ("
            "id BIGINT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "source VARCHAR(40) NOT NULL)"
        )
    )
    await db_session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_catalog_entry_clicks_source_occurred "
            "ON catalog_entry_clicks (source, occurred_at)"
        )
    )
    (event_id,) = (
        await db_session.execute(
            text("INSERT INTO client_share_events (kind) VALUES (:kind) RETURNING id"),
            {"kind": kind},
        )
    ).one()
    downgrade = runpy.run_path(str(MIGRATIONS / migration_file))["downgrade"]
    connection = await db_session.connection()

    def invoke_downgrade(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            downgrade()

    with pytest.raises(RuntimeError, match=rf"Cannot downgrade .*kind='{kind}'.*history"):
        await connection.run_sync(invoke_downgrade)

    stored_kind = await db_session.scalar(
        text("SELECT kind FROM client_share_events WHERE id = :event_id"),
        {"event_id": event_id},
    )
    assert stored_kind == kind

    constraint = await db_session.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_client_share_events_kind' "
            "AND conrelid = 'client_share_events'::regclass"
        )
    )
    assert kind in constraint
