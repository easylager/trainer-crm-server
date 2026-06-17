"""O5.6: center session booking notification routing (ADR-003 §4.1)."""
from datetime import date, datetime, time, timezone

import pytest

pytestmark = pytest.mark.collective
from sqlalchemy import text

from src.application.collective_session_booking_notify import (
    resolve_collective_session_booking_notify_trainer_ids,
)
from src.application.collective_session_use_cases import (
    ATTENDANCE_COACH_INDIVIDUAL,
    ATTENDANCE_LANE_SELF,
    create_collective_session,
)
from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_ADMIN,
    MEMBER_ROLE_MEMBER,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    SCHEDULE_MODE_STUDIO_CENTRAL,
    promote_collective_member_to_admin,
)


async def _seed_center_with_team(db_session) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (
                slug, display_name, status, seat_limit, schedule_mode, created_at, updated_at
            )
            VALUES ('notify-center', 'Notify Center', :st, 8, :mode, :now, :now)
            RETURNING id
            """
        ),
        {"st": COLLECTIVE_STATUS_ACTIVE, "mode": SCHEDULE_MODE_STUDIO_CENTRAL, "now": now},
    )
    cid = int(r.scalar_one())

    async def _trainer() -> int:
        rr = await db_session.execute(
            text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
            {"now": now},
        )
        return int(rr.scalar_one())

    owner_id = await _trainer()
    admin_id = await _trainer()
    duty_coach_id = await _trainer()

    await db_session.execute(
        text("UPDATE collectives SET owner_trainer_id = :tid WHERE id = :cid"),
        {"tid": owner_id, "cid": cid},
    )

    async def _member(tid: int, role: str) -> None:
        await db_session.execute(
            text(
                """
                INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
                VALUES (:cid, :tid, :role, :active, :now)
                """
            ),
            {
                "cid": cid,
                "tid": tid,
                "role": role,
                "active": MEMBER_STATUS_ACTIVE,
                "now": now,
            },
        )

    await _member(owner_id, MEMBER_ROLE_OWNER)
    await _member(admin_id, MEMBER_ROLE_MEMBER)
    await _member(duty_coach_id, MEMBER_ROLE_MEMBER)
    await promote_collective_member_to_admin(db_session, cid, owner_id, admin_id)

    session_row = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=date.today(),
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=4,
        coach_trainer_ids=[duty_coach_id],
    )
    assert session_row and session_row.get("id")
    await db_session.commit()
    return {
        "collective_id": cid,
        "owner_id": owner_id,
        "admin_id": admin_id,
        "duty_coach_id": duty_coach_id,
    }


@pytest.mark.asyncio
async def test_lane_booking_notifies_studio_admins_not_duty_coach(db_session) -> None:
    ctx = await _seed_center_with_team(db_session)
    targets = await resolve_collective_session_booking_notify_trainer_ids(
        db_session,
        collective_id=ctx["collective_id"],
        attendance_mode=ATTENDANCE_LANE_SELF,
        center_coach_id=None,
        fulfillment_trainer_id=ctx["owner_id"],
    )
    assert ctx["duty_coach_id"] not in targets
    assert ctx["owner_id"] in targets
    assert ctx["admin_id"] in targets


@pytest.mark.asyncio
async def test_coach_booking_notifies_assigned_coach_only(db_session) -> None:
    ctx = await _seed_center_with_team(db_session)
    targets = await resolve_collective_session_booking_notify_trainer_ids(
        db_session,
        collective_id=ctx["collective_id"],
        attendance_mode=ATTENDANCE_COACH_INDIVIDUAL,
        center_coach_id=ctx["duty_coach_id"],
        fulfillment_trainer_id=ctx["duty_coach_id"],
    )
    assert targets == [ctx["duty_coach_id"]]
