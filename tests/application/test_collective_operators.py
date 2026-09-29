"""TASK-141 (S1): collective_operators (org bot claim), separate identity axis from coach.

AC-001: org claim creates collective_operators, never a trainers row.
AC-002: claim deep link points at the org bot, not the trainer bot.
AC-004: an existing coach (trainer_id) can claim an org separately — two independent identities.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    OPERATOR_ROLE_OWNER,
    OPERATOR_STATUS_ACTIVE,
    consume_collective_claim_token_for_operator,
    create_collective_draft,
    issue_collective_claim_token,
    resolve_operator_membership,
)
from src.shared.config import Settings

pytestmark = pytest.mark.collective


def _fresh_telegram_id() -> int:
    import random

    return random.randint(9_000_000_000, 9_999_999_999)


@pytest.mark.asyncio
async def test_org_claim_creates_operator_not_trainer(db_session) -> None:
    telegram_id = _fresh_telegram_id()
    created = await create_collective_draft(
        db_session, slug="org-claim-basic", display_name="Basic School"
    )
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    assert claim is not None

    result = await consume_collective_claim_token_for_operator(db_session, claim["token"], telegram_id)
    assert result.error is None
    assert result.collective_id == int(created["id"])

    op_row = await db_session.execute(
        text(
            "SELECT role, status FROM collective_operators WHERE collective_id = :cid AND telegram_id = :tgid"
        ),
        {"cid": created["id"], "tgid": telegram_id},
    )
    row = op_row.fetchone()
    assert row is not None
    assert str(row[0]) == OPERATOR_ROLE_OWNER
    assert str(row[1]) == OPERATOR_STATUS_ACTIVE

    coll_row = await db_session.execute(
        text("SELECT status, owner_trainer_id FROM collectives WHERE id = :cid"),
        {"cid": created["id"]},
    )
    coll = coll_row.fetchone()
    assert str(coll[0]) == COLLECTIVE_STATUS_ACTIVE
    assert coll[1] is None  # owner_trainer_id stays null for org-bot claims

    trainer_row = await db_session.execute(
        text("SELECT COUNT(*) FROM trainers WHERE telegram_id = :tgid"),
        {"tgid": telegram_id},
    )
    assert int(trainer_row.scalar_one()) == 0


@pytest.mark.asyncio
async def test_org_claim_rejects_when_not_draft(db_session) -> None:
    telegram_id = _fresh_telegram_id()
    created = await create_collective_draft(
        db_session, slug="org-claim-not-draft", display_name="Already Active"
    )
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    first = await consume_collective_claim_token_for_operator(db_session, claim["token"], telegram_id)
    assert first.error is None

    claim2 = await issue_collective_claim_token(db_session, int(created["id"]))
    assert claim2 is None  # issue_collective_claim_token itself refuses non-draft collectives


@pytest.mark.asyncio
async def test_org_claim_second_distinct_telegram_rejects_as_already_claimed(db_session) -> None:
    owner_tgid = _fresh_telegram_id()
    other_tgid = _fresh_telegram_id()
    created = await create_collective_draft(
        db_session, slug="org-claim-race", display_name="Contested School"
    )
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    first = await consume_collective_claim_token_for_operator(db_session, claim["token"], owner_tgid)
    assert first.error is None

    # Same (now-used) token can't be replayed by a second telegram_id — token itself is single-use.
    second = await consume_collective_claim_token_for_operator(db_session, claim["token"], other_tgid)
    assert second.error == "invalid_token"


def test_claim_deep_link_points_to_org_bot_not_trainer_bot() -> None:
    settings = Settings()
    org_uname = (settings.org_bot_username or "").strip()
    trainer_uname = (settings.trainer_bot_username or "").strip()
    assert org_uname, "ORG_BOT_USERNAME must be set for this test"
    assert org_uname != trainer_uname


@pytest.mark.asyncio
async def test_existing_coach_can_claim_org_separately(db_session) -> None:
    """AC-004: one telegram_id, two independent identities — coach membership
    (collective_members, keyed by trainer_id) is untouched by an org operator claim
    (collective_operators, keyed by telegram_id) for the same person."""
    telegram_id = _fresh_telegram_id()
    now = datetime.now(timezone.utc)
    r_tr = await db_session.execute(
        text(
            "INSERT INTO trainers (status, telegram_id, studio_access_mode, created_at) "
            "VALUES ('active', :tgid, 'full_trainer', :now) RETURNING id"
        ),
        {"tgid": telegram_id, "now": now},
    )
    trainer_id = int(r_tr.scalar_one())

    created = await create_collective_draft(
        db_session, slug="org-claim-owner-coach", display_name="Owner Coach School"
    )
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    result = await consume_collective_claim_token_for_operator(db_session, claim["token"], telegram_id)
    assert result.error is None

    # Operator row created for this telegram_id.
    membership = await resolve_operator_membership(db_session, telegram_id)
    assert membership is not None
    assert membership.role == OPERATOR_ROLE_OWNER

    # Trainer row untouched: no collective_members row, studio_access_mode unchanged.
    member_row = await db_session.execute(
        text("SELECT COUNT(*) FROM collective_members WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    assert int(member_row.scalar_one()) == 0
    mode_row = await db_session.execute(
        text("SELECT studio_access_mode FROM trainers WHERE id = :tid"),
        {"tid": trainer_id},
    )
    assert str(mode_row.scalar_one()) == "full_trainer"
