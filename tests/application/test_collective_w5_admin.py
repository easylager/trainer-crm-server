"""W5: studio admin role, booking contexts, delegate booking, studio_admin_only (ADR-003 §6–§7)."""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.collective_booking_context_use_cases import (
    assert_delegate_personal_slot_booking,
    create_staff_center_session_booking,
    list_staff_bookable_center_sessions,
    list_trainer_booking_contexts,
)
from src.application.collective_session_use_cases import (
    ATTENDANCE_LANE_SELF,
    create_collective_session,
)
from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_ADMIN,
    MEMBER_ROLE_MEMBER,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    SCHEDULE_MODE_MEMBER_AUTONOMOUS,
    SCHEDULE_MODE_STUDIO_CENTRAL,
    STUDIO_ACCESS_MODE_ADMIN_ONLY,
    promote_collective_member_to_admin,
)
from src.application.trainer_onboarding_checklist import get_trainer_onboarding_checklist

pytestmark = pytest.mark.collective


async def _seed_trainer(db_session) -> int:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    tid = int(r.scalar_one())
    await db_session.commit()
    return tid


async def _seed_collective(
    db_session,
    *,
    slug: str,
    owner_id: int,
    schedule_mode: str,
) -> int:
    now = datetime.now(timezone.utc)
    r_col = await db_session.execute(
        text(
            """
            INSERT INTO collectives (
                slug, display_name, status, seat_limit, owner_trainer_id,
                schedule_mode, created_at, updated_at
            )
            VALUES (:slug, :name, :st, 5, :oid, :mode, :now, :now)
            RETURNING id
            """
        ),
        {
            "slug": slug,
            "name": slug,
            "st": COLLECTIVE_STATUS_ACTIVE,
            "oid": owner_id,
            "mode": schedule_mode,
            "now": now,
        },
    )
    cid = int(r_col.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :owner, :active, :now)
            """
        ),
        {
            "cid": cid,
            "tid": owner_id,
            "owner": MEMBER_ROLE_OWNER,
            "active": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await db_session.commit()
    return cid


async def _seed_member(
    db_session,
    *,
    collective_id: int,
    trainer_id: int,
    role: str = MEMBER_ROLE_MEMBER,
) -> None:
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :role, :active, :now)
            """
        ),
        {
            "cid": collective_id,
            "tid": trainer_id,
            "role": role,
            "active": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await db_session.commit()


async def _seed_client(db_session) -> int:
    r = await db_session.execute(
        text("INSERT INTO clients (telegram_id, created_at) VALUES (910001, NOW()) RETURNING id")
    )
    cid = int(r.scalar_one())
    await db_session.commit()
    return cid


async def _seed_slot(db_session, *, trainer_id: int, slot_date: date) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, '10:00', '11:00', 'available', 1)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    sid = int(r.scalar_one())
    await db_session.commit()
    return sid


@pytest.mark.asyncio
async def test_owner_promotes_member_to_admin(db_session) -> None:
    owner_id = await _seed_trainer(db_session)
    coach_id = await _seed_trainer(db_session)
    cid = await _seed_collective(
        db_session,
        slug="promote-center",
        owner_id=owner_id,
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
    )
    await _seed_member(db_session, collective_id=cid, trainer_id=coach_id)

    result = await promote_collective_member_to_admin(db_session, cid, owner_id, coach_id)
    assert result.get("error") is None
    assert result["role"] == MEMBER_ROLE_ADMIN

    dup = await promote_collective_member_to_admin(db_session, cid, owner_id, coach_id)
    assert dup.get("error") == "already_admin"


@pytest.mark.asyncio
async def test_booking_contexts_multi_studio_and_center(db_session) -> None:
    coach_id = await _seed_trainer(db_session)
    ice_owner = await _seed_trainer(db_session)
    center_owner = await _seed_trainer(db_session)

    ice_id = await _seed_collective(
        db_session,
        slug="ice-yoga",
        owner_id=ice_owner,
        schedule_mode=SCHEDULE_MODE_MEMBER_AUTONOMOUS,
    )
    await _seed_member(db_session, collective_id=ice_id, trainer_id=coach_id)

    center_id = await _seed_collective(
        db_session,
        slug="throw-hub",
        owner_id=center_owner,
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
    )
    await _seed_member(db_session, collective_id=center_id, trainer_id=coach_id, role=MEMBER_ROLE_ADMIN)

    slot_date = date.today() + timedelta(days=5)
    created = await create_collective_session(
        db_session,
        collective_id=center_id,
        owner_trainer_id=center_owner,
        slot_date=slot_date,
        start_time=time(12, 0),
        end_time=time(13, 0),
        coach_trainer_ids=[coach_id],
    )
    assert created and created.get("error") is None

    payload = await list_trainer_booking_contexts(db_session, coach_id)
    assert payload["needs_context_picker"] is True
    kinds = {c["kind"] for c in payload["contexts"]}
    assert "personal_slot" in kinds
    assert "center_session" in kinds
    assert payload["delegate"] is not None
    assert payload["delegate"]["collective_slug"] == "throw-hub"
    assert any(c["trainer_id"] == coach_id for c in payload["delegate"]["coaches"])


@pytest.mark.asyncio
async def test_booking_contexts_admin_only_owner_keeps_personal_and_center(db_session) -> None:
    owner_id = await _seed_trainer(db_session)
    await db_session.execute(
        text("UPDATE trainers SET studio_access_mode = :mode WHERE id = :tid"),
        {"mode": STUDIO_ACCESS_MODE_ADMIN_ONLY, "tid": owner_id},
    )
    await db_session.commit()

    center_id = await _seed_collective(
        db_session,
        slug="ops-desk",
        owner_id=owner_id,
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
    )
    slot_date = date.today() + timedelta(days=4)
    created = await create_collective_session(
        db_session,
        collective_id=center_id,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(10, 0),
        end_time=time(11, 0),
        coach_trainer_ids=[owner_id],
    )
    assert created and created.get("error") is None

    payload = await list_trainer_booking_contexts(db_session, owner_id)
    assert payload["needs_context_picker"] is True
    kinds = {c["kind"] for c in payload["contexts"]}
    assert "personal_slot" in kinds
    assert "center_session" in kinds
    center_ctx = next(c for c in payload["contexts"] if c["kind"] == "center_session")
    assert "через центр" in center_ctx["label"]


@pytest.mark.asyncio
async def test_delegate_personal_slot_booking_by_studio_admin(db_session) -> None:
    owner_id = await _seed_trainer(db_session)
    admin_id = await _seed_trainer(db_session)
    coach_id = await _seed_trainer(db_session)
    cid = await _seed_collective(
        db_session,
        slug="delegate-slot",
        owner_id=owner_id,
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
    )
    await _seed_member(db_session, collective_id=cid, trainer_id=admin_id, role=MEMBER_ROLE_ADMIN)
    await _seed_member(db_session, collective_id=cid, trainer_id=coach_id)

    slot_date = date.today() + timedelta(days=6)
    slot_id = await _seed_slot(db_session, trainer_id=coach_id, slot_date=slot_date)

    err = await assert_delegate_personal_slot_booking(
        db_session,
        actor_trainer_id=admin_id,
        target_trainer_id=coach_id,
        slot_id=slot_id,
        collective_slug="delegate-slot",
    )
    assert err is None

    wrong_slot = await assert_delegate_personal_slot_booking(
        db_session,
        actor_trainer_id=admin_id,
        target_trainer_id=owner_id,
        slot_id=slot_id,
        collective_slug="delegate-slot",
    )
    assert wrong_slot == "slot_not_target_trainer"

    member_err = await assert_delegate_personal_slot_booking(
        db_session,
        actor_trainer_id=coach_id,
        target_trainer_id=coach_id,
        slot_id=slot_id,
        collective_slug="delegate-slot",
    )
    assert member_err is None


@pytest.mark.asyncio
async def test_admin_staff_center_session_booking(db_session) -> None:
    owner_id = await _seed_trainer(db_session)
    admin_id = await _seed_trainer(db_session)
    cid = await _seed_collective(
        db_session,
        slug="staff-book",
        owner_id=owner_id,
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
    )
    await _seed_member(db_session, collective_id=cid, trainer_id=admin_id, role=MEMBER_ROLE_ADMIN)
    client_id = await _seed_client(db_session)

    slot_date = date.today() + timedelta(days=4)
    created = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(15, 0),
        end_time=time(16, 0),
    )
    session_id = int(created["id"])

    listed = await list_staff_bookable_center_sessions(
        db_session,
        actor_trainer_id=admin_id,
        collective_slug="staff-book",
    )
    assert listed.get("error") is None
    assert any(int(s["id"]) == session_id for s in listed["sessions"])

    booked = await create_staff_center_session_booking(
        db_session,
        actor_trainer_id=admin_id,
        collective_slug="staff-book",
        session_id=session_id,
        client_id=client_id,
        attendance_mode=ATTENDANCE_LANE_SELF,
    )
    assert booked.get("error") is None
    assert booked["status"] == "confirmed"


@pytest.mark.asyncio
async def test_studio_admin_only_skips_trainer_onboarding_gates(db_session) -> None:
    manager_id = await _seed_trainer(db_session)
    await db_session.execute(
        text(
            """
            UPDATE trainers SET studio_access_mode = :mode, status = 'pending_profile'
            WHERE id = :tid
            """
        ),
        {"mode": STUDIO_ACCESS_MODE_ADMIN_ONLY, "tid": manager_id},
    )
    await db_session.commit()

    checklist = await get_trainer_onboarding_checklist(db_session, manager_id)
    assert checklist["studio_access_mode"] == STUDIO_ACCESS_MODE_ADMIN_ONLY
    assert checklist["schedule_unlocked"] is True
    assert checklist["tt_minimal_complete"] is True
    assert checklist["has_any_booking"] is True
    # Studio manager never submits their own card for moderation — step 3 must not strand them.
    assert checklist["moderation_submitted"] is True
    assert checklist["slots_locked_reason"] is None
