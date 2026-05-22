"""Platform audit log: persist + admin list."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.platform_audit_use_cases import (
    insert_platform_audit_from_record,
    list_platform_audit_events_for_admin,
)
from src.shared.audit import ACTOR_CLIENT_BOT, audit_log


@pytest.fixture(autouse=True)
async def _require_platform_audit_table(db_session: AsyncSession) -> None:
    try:
        await db_session.execute(text("SELECT 1 FROM platform_audit_events LIMIT 1"))
    except ProgrammingError:
        pytest.skip("Run migration 0154_platform_audit")


@pytest.mark.asyncio
async def test_insert_and_list_audit_event(db_session: AsyncSession) -> None:
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, schedule_grid_step_minutes)
            VALUES ('active', 15)
            RETURNING id
            """
        )
    )
    trainer_id = int(r.scalar_one())
    eid = await insert_platform_audit_from_record(
        db_session,
        {
            "event": "booking.created",
            "actor_type": "client_bot",
            "actor_id": "12345",
            "payload": {"booking_id": 99, "trainer_id": trainer_id, "slot_id": 3},
        },
    )
    await db_session.commit()
    assert eid is not None

    data = await list_platform_audit_events_for_admin(db_session, limit=10, trainer_id=trainer_id)
    assert data["events"]
    top = data["events"][0]
    assert top["event_type"] == "booking.created"
    assert top["trainer_id"] == trainer_id


@pytest.mark.asyncio
async def test_audit_log_skips_background_persist_under_pytest(db_session: AsyncSession) -> None:
    """Background persist is disabled in pytest (single shared asyncpg connection)."""
    before = await db_session.execute(text("SELECT COUNT(*) FROM platform_audit_events"))
    n0 = int(before.scalar() or 0)

    audit_log(
        "client_request.created",
        ACTOR_CLIENT_BOT,
        555,
        {"request_id": 1, "city_id": 2, "service_id": 3},
    )
    await asyncio.sleep(0.05)

    after = await db_session.execute(text("SELECT COUNT(*) FROM platform_audit_events"))
    n1 = int(after.scalar() or 0)
    assert n1 == n0


@pytest.mark.asyncio
async def test_persist_audit_record_direct(db_session: AsyncSession) -> None:
    before = await db_session.execute(text("SELECT COUNT(*) FROM platform_audit_events"))
    n0 = int(before.scalar() or 0)

    eid = await insert_platform_audit_from_record(
        db_session,
        {
            "event": "client_request.created",
            "actor_type": ACTOR_CLIENT_BOT,
            "actor_id": "555",
            "payload": {"request_id": 42, "city_id": 2, "service_id": 3},
        },
    )
    await db_session.commit()
    assert eid is not None

    after = await db_session.execute(text("SELECT COUNT(*) FROM platform_audit_events"))
    n1 = int(after.scalar() or 0)
    assert n1 >= n0 + 1
