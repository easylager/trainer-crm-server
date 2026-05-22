"""Activation funnel signals for client invite sharing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.admin_analytics_use_cases import get_admin_product_analytics
from src.application.trainer_client_invite_tracking import (
    record_trainer_client_invite_link_first_copy,
    sql_trainer_shared_client_invite,
    sql_trainer_submitted_for_moderation,
)


async def _insert_trainer_with_client_in_bot(session: AsyncSession) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO trainers (status, schedule_grid_step_minutes)
            VALUES ('active', 15)
            RETURNING id
            """
        )
    )
    trainer_id = int(r.scalar_one())
    r2 = await session.execute(
        text(
            """
            INSERT INTO clients (first_name, phone, phone_normalized, telegram_id, is_sandbox)
            VALUES ('Test', '+375291234567', '+375291234567', 999001, false)
            RETURNING id
            """
        )
    )
    client_id = int(r2.scalar_one())
    await session.execute(
        text(
            """
            INSERT INTO trainer_client_roster (trainer_id, client_id)
            VALUES (:tid, :cid)
            ON CONFLICT DO NOTHING
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    await session.commit()
    return trainer_id


@pytest.mark.asyncio
async def test_shared_invite_sql_counts_client_in_bot(db_session: AsyncSession) -> None:
    trainer_id = await _insert_trainer_with_client_in_bot(db_session)

    r2 = await db_session.execute(
        text(
            f"""
            SELECT {sql_trainer_shared_client_invite()}
            FROM trainers t WHERE t.id = :id
            """
        ),
        {"id": trainer_id},
    )
    assert r2.scalar_one() is True


@pytest.mark.asyncio
async def test_submitted_moderation_sql_counts_active_without_timestamp(db_session: AsyncSession) -> None:
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, schedule_grid_step_minutes, moderation_submitted_at)
            VALUES ('active', 15, NULL)
            RETURNING id
            """
        )
    )
    trainer_id = int(r.scalar_one())
    await db_session.commit()

    r2 = await db_session.execute(
        text(
            f"""
            SELECT {sql_trainer_submitted_for_moderation()}
            FROM trainers t WHERE t.id = :id
            """
        ),
        {"id": trainer_id},
    )
    assert r2.scalar_one() is True


@pytest.mark.asyncio
async def test_product_analytics_funnel_active_implies_submitted_moderation(db_session: AsyncSession) -> None:
    before = await get_admin_product_analytics(db_session)
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, schedule_grid_step_minutes, telegram_id, created_at)
            VALUES ('active', 15, 123456789, :created_at)
            RETURNING id
            """
        ),
        {"created_at": datetime.now(timezone.utc) - timedelta(days=30)},
    )
    trainer_id = int(r.scalar_one())
    r2 = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, phone, phone_normalized, telegram_id, is_sandbox)
            VALUES ('A', '+375291111111', '+375291111111', 888001, false)
            RETURNING id
            """
        )
    )
    client_id = int(r2.scalar_one())
    await db_session.execute(
        text(
            "INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:tid, :cid)"
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    await db_session.commit()

    after = await get_admin_product_analytics(db_session)
    af = after.get("activation_funnel") or {}
    assert af.get("activated", 0) >= before.get("activation_funnel", {}).get("activated", 0) + 1
    assert af.get("submitted_moderation", 0) >= af.get("activated", 0)
    assert af.get("copied_invite", 0) >= 1


@pytest.mark.asyncio
async def test_record_first_copy_idempotent(db_session: AsyncSession) -> None:
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, schedule_grid_step_minutes)
            VALUES ('pending_profile', 15)
            RETURNING id
            """
        )
    )
    trainer_id = int(r.scalar_one())
    await db_session.commit()

    ts1 = await record_trainer_client_invite_link_first_copy(db_session, trainer_id)
    ts2 = await record_trainer_client_invite_link_first_copy(db_session, trainer_id)
    assert ts1 is not None
    assert ts2 == ts1
