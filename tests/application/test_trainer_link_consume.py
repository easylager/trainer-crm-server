"""Trainer welcome link token consumption."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.application.trainer_link import consume_link_token
from src.application.trainer_link_token_use_cases import issue_landing_trainer_link_token
from src.infrastructure.db.models import TRAINER_STATUS_PENDING_PROFILE


@pytest.mark.asyncio
async def test_consume_landing_token_creates_trainer_on_first_open(db_session) -> None:
    before = await db_session.execute(text("SELECT COUNT(*) FROM trainers"))
    trainers_before = int(before.scalar() or 0)

    issued = await issue_landing_trainer_link_token(db_session)
    token = str(issued["token"])
    telegram_id = 9_001_001_001

    out = await consume_link_token(db_session, token, telegram_id, telegram_username="coach_test")
    assert out.error is None
    assert out.trainer_id is not None

    after = await db_session.execute(text("SELECT COUNT(*) FROM trainers"))
    assert int(after.scalar() or 0) == trainers_before + 1

    row = await db_session.execute(
        text("SELECT status, telegram_id FROM trainers WHERE id = :id"),
        {"id": out.trainer_id},
    )
    trainer = row.fetchone()
    assert trainer is not None
    assert trainer[0] == TRAINER_STATUS_PENDING_PROFILE
    assert int(trainer[1]) == telegram_id


@pytest.mark.asyncio
async def test_consume_landing_token_idempotent_for_linked_telegram(db_session) -> None:
    issued = await issue_landing_trainer_link_token(db_session)
    token = str(issued["token"])
    telegram_id = 9_001_001_002

    first = await consume_link_token(db_session, token, telegram_id)
    assert first.trainer_id is not None

    issued2 = await issue_landing_trainer_link_token(db_session)
    second = await consume_link_token(db_session, str(issued2["token"]), telegram_id)
    assert second.error is None
    assert second.trainer_id == first.trainer_id
