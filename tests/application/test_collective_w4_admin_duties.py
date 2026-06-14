"""Collective admin inbox, center duties overlay (ADR §6), solo trainer unchanged."""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.collective_session_use_cases import (
    ATTENDANCE_LANE_SELF,
    BOOKING_STATUS_PENDING,
    create_collective_session,
    create_collective_session_booking,
    decline_collective_session_booking,
    list_center_duties_for_trainer,
    list_pending_collective_session_bookings_for_owner,
)
from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_MEMBER,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    SCHEDULE_MODE_STUDIO_CENTRAL,
)

pytestmark = pytest.mark.collective


async def _seed_studio(db_session, *, slug: str = "admin-inbox") -> tuple[int, int, int]:
    now = datetime.now(timezone.utc)
    r_owner = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    owner_id = int(r_owner.scalar_one())
    r_coach = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    coach_id = int(r_coach.scalar_one())
    r_col = await db_session.execute(
        text(
            """
            INSERT INTO collectives (
                slug, display_name, status, seat_limit, owner_trainer_id,
                schedule_mode, created_at, updated_at
            )
            VALUES (:slug, 'Center', :st, 5, :oid, :mode, :now, :now)
            RETURNING id
            """
        ),
        {
            "slug": slug,
            "st": COLLECTIVE_STATUS_ACTIVE,
            "oid": owner_id,
            "mode": SCHEDULE_MODE_STUDIO_CENTRAL,
            "now": now,
        },
    )
    cid = int(r_col.scalar_one())
    for tid, role in ((owner_id, MEMBER_ROLE_OWNER), (coach_id, MEMBER_ROLE_MEMBER)):
        await db_session.execute(
            text(
                """
                INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
                VALUES (:cid, :tid, :role, :active, :now)
                """
            ),
            {"cid": cid, "tid": tid, "role": role, "active": MEMBER_STATUS_ACTIVE, "now": now},
        )
    await db_session.commit()
    return cid, owner_id, coach_id


@pytest.mark.asyncio
async def test_solo_trainer_has_no_center_duties(db_session) -> None:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    solo_id = int(r.scalar_one())
    await db_session.commit()
    duties = await list_center_duties_for_trainer(
        db_session,
        trainer_id=solo_id,
        from_date=date.today(),
        to_date=date.today() + timedelta(days=14),
    )
    assert duties == []


@pytest.mark.asyncio
async def test_center_duty_listed_for_assigned_coach(db_session) -> None:
    cid, owner_id, coach_id = await _seed_studio(db_session, slug="duty-coach")
    slot_date = date.today() + timedelta(days=2)
    created = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(14, 0),
        end_time=time(15, 0),
        coach_trainer_ids=[coach_id],
    )
    assert created and created.get("error") is None

    duties = await list_center_duties_for_trainer(
        db_session,
        trainer_id=coach_id,
        from_date=slot_date,
        to_date=slot_date,
    )
    assert len(duties) == 1
    assert duties[0]["collective_session_id"] == int(created["id"])
    assert duties[0]["kind"] == "center_duty"

    owner_duties = await list_center_duties_for_trainer(
        db_session,
        trainer_id=owner_id,
        from_date=slot_date,
        to_date=slot_date,
    )
    assert owner_duties == []


@pytest.mark.asyncio
async def test_owner_inbox_lists_pending_booking(db_session) -> None:
    cid, owner_id, coach_id = await _seed_studio(db_session, slug="inbox-test")
    slot_date = date.today() + timedelta(days=3)
    created = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(10, 0),
        end_time=time(11, 0),
    )
    session_id = int(created["id"])

    r_client = await db_session.execute(
        text("INSERT INTO clients (telegram_id, created_at) VALUES (920001, NOW()) RETURNING id")
    )
    client_id = int(r_client.scalar_one())
    await db_session.commit()

    booking = await create_collective_session_booking(
        db_session,
        session_id=session_id,
        client_id=client_id,
        attendance_mode=ATTENDANCE_LANE_SELF,
    )
    assert booking and booking["status"] == BOOKING_STATUS_PENDING

    inbox = await list_pending_collective_session_bookings_for_owner(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
    )
    assert inbox.get("error") is None
    assert inbox["count"] == 1
    assert inbox["bookings"][0]["booking_id"] == int(booking["booking_id"])
    assert inbox["bookings"][0]["attendance_mode_label"] == "Дорожка"

    declined = await decline_collective_session_booking(
        db_session,
        booking_id=int(booking["booking_id"]),
        trainer_id=owner_id,
    )
    assert declined and declined.get("ok")

    inbox2 = await list_pending_collective_session_bookings_for_owner(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
    )
    assert inbox2["count"] == 0
