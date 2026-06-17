"""Collective Wave P1.8: team governance (remove, transfer, revoke invites)."""
from datetime import datetime, timezone, date

import pytest

pytestmark = pytest.mark.collective
from sqlalchemy import text

from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_MEMBER,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    MEMBER_STATUS_LEFT,
    count_pending_collective_invite_tokens,
    get_active_collective_membership,
    issue_collective_invite_token,
    remove_collective_member,
    revoke_pending_collective_invites,
    transfer_collective_ownership,
)


async def _seed_studio_with_owner_and_member(db_session) -> tuple[int, int, int]:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, status, seat_limit, created_at, updated_at)
            VALUES ('gov-studio', 'Gov Studio', :st, 5, :now, :now)
            RETURNING id
            """
        ),
        {"st": COLLECTIVE_STATUS_ACTIVE, "now": now},
    )
    cid = int(r.scalar_one())
    r_owner = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    owner_id = int(r_owner.scalar_one())
    r_member = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    member_id = int(r_member.scalar_one())
    await db_session.execute(
        text("UPDATE collectives SET owner_trainer_id = :tid WHERE id = :cid"),
        {"tid": owner_id, "cid": cid},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :role, :active, :now)
            """
        ),
        {"cid": cid, "tid": owner_id, "role": MEMBER_ROLE_OWNER, "active": MEMBER_STATUS_ACTIVE, "now": now},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :role, :active, :now)
            """
        ),
        {"cid": cid, "tid": member_id, "role": MEMBER_ROLE_MEMBER, "active": MEMBER_STATUS_ACTIVE, "now": now},
    )
    await db_session.commit()
    return cid, owner_id, member_id


@pytest.mark.asyncio
async def test_remove_collective_member(db_session) -> None:
    cid, owner_id, member_id = await _seed_studio_with_owner_and_member(db_session)

    removed = await remove_collective_member(db_session, cid, owner_id, member_id)
    assert removed.get("removed_trainer_id") == member_id
    assert await get_active_collective_membership(db_session, member_id) is None

    row = await db_session.execute(
        text("SELECT status FROM collective_members WHERE collective_id = :cid AND trainer_id = :tid"),
        {"cid": cid, "tid": member_id},
    )
    assert str(row.scalar_one()) == MEMBER_STATUS_LEFT


@pytest.mark.asyncio
async def test_transfer_collective_ownership(db_session) -> None:
    cid, owner_id, member_id = await _seed_studio_with_owner_and_member(db_session)

    transferred = await transfer_collective_ownership(db_session, cid, owner_id, member_id)
    assert transferred.get("new_owner_trainer_id") == member_id

    owner_membership = await get_active_collective_membership(db_session, owner_id)
    new_owner_membership = await get_active_collective_membership(db_session, member_id)
    assert owner_membership is not None
    assert owner_membership.role == MEMBER_ROLE_MEMBER
    assert new_owner_membership is not None
    assert new_owner_membership.role == MEMBER_ROLE_OWNER

    owner_row = await db_session.execute(
        text("SELECT owner_trainer_id FROM collectives WHERE id = :cid"),
        {"cid": cid},
    )
    assert int(owner_row.scalar_one()) == member_id


@pytest.mark.asyncio
async def test_revoke_pending_collective_invites(db_session) -> None:
    cid, owner_id, _member_id = await _seed_studio_with_owner_and_member(db_session)
    issued = await issue_collective_invite_token(db_session, cid, owner_id)
    assert issued is not None
    assert await count_pending_collective_invite_tokens(db_session, cid) == 1

    revoked = await revoke_pending_collective_invites(db_session, cid, owner_id)
    assert revoked.get("revoked_count") == 1
    assert await count_pending_collective_invite_tokens(db_session, cid) == 0


@pytest.mark.asyncio
async def test_cannot_remove_owner(db_session) -> None:
    cid, owner_id, _member_id = await _seed_studio_with_owner_and_member(db_session)
    result = await remove_collective_member(db_session, cid, owner_id, owner_id)
    assert result.get("error") == "cannot_remove_self"


@pytest.mark.asyncio
async def test_preview_collective_member_removal(db_session) -> None:
    from datetime import time as time_type

    from src.application.collective_session_use_cases import create_collective_session
    from src.application.collective_use_cases import (
        SCHEDULE_MODE_STUDIO_CENTRAL,
        preview_collective_member_removal,
    )

    cid, owner_id, member_id = await _seed_studio_with_owner_and_member(db_session)
    await db_session.execute(
        text("UPDATE collectives SET schedule_mode = :mode WHERE id = :cid"),
        {"mode": SCHEDULE_MODE_STUDIO_CENTRAL, "cid": cid},
    )
    await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=date.today(),
        start_time=time_type(10, 0),
        end_time=time_type(11, 0),
        coach_trainer_ids=[member_id],
    )
    preview = await preview_collective_member_removal(db_session, cid, owner_id, member_id)
    assert preview.get("future_duty_sessions", 0) >= 1
    assert preview.get("warnings")
