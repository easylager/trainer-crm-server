"""Catalog-listed invite push eligibility."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from src.application.trainer_catalog_listed_invite_push_use_cases import (
    list_due_catalog_listed_invite_pushes,
    mark_catalog_listed_invite_push_sent,
)
from src.infrastructure.db.models import CATALOG_STATE_PUBLISHED


@pytest.mark.asyncio
async def test_list_due_excludes_after_mark_sent(db_session) -> None:
    r = await db_session.execute(text("INSERT INTO trainers (created_at) VALUES (now()) RETURNING id"))
    trainer_id = int(r.fetchone()[0])
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age)
            VALUES (:tid, 'A', 'B', 30)
            """
        ),
        {"tid": trainer_id},
    )
    await db_session.execute(
        text(
            """
            UPDATE trainers SET
                telegram_id = 900001,
                catalog_state = :st,
                catalog_state_changed_at = NOW() - INTERVAL '4 hours',
                status = 'active'
            WHERE id = :tid
            """
        ),
        {"tid": trainer_id, "st": CATALOG_STATE_PUBLISHED},
    )
    await db_session.commit()

    due = await list_due_catalog_listed_invite_pushes(db_session)
    assert any(d.trainer_id == trainer_id for d in due)

    ok = await mark_catalog_listed_invite_push_sent(db_session, trainer_id)
    assert ok is True

    due2 = await list_due_catalog_listed_invite_pushes(db_session)
    assert not any(d.trainer_id == trainer_id for d in due2)
