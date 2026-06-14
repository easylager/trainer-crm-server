"""W4 multi-collective membership + center duty slot conflicts (ADR-003 §5–§6)."""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.collective_session_use_cases import (
    assert_no_center_duty_conflict_for_slots,
    create_collective_session,
)
from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_MEMBER,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    SCHEDULE_MODE_MEMBER_AUTONOMOUS,
    SCHEDULE_MODE_STUDIO_CENTRAL,
    build_trainer_collective_bootstrap_payload,
    list_active_collective_memberships,
    resolve_collective_membership,
)

pytestmark = pytest.mark.collective


async def _seed_collective(
    db_session,
    *,
    slug: str,
    owner_id: int,
    schedule_mode: str = SCHEDULE_MODE_MEMBER_AUTONOMOUS,
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


async def _seed_member(db_session, *, collective_id: int, trainer_id: int) -> None:
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
            "role": MEMBER_ROLE_MEMBER,
            "active": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_trainer_can_have_two_active_memberships(db_session) -> None:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    trainer_id = int(r.scalar_one())
    await _seed_collective(db_session, slug="ice-studio", owner_id=trainer_id)
    r_owner = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    center_owner = int(r_owner.scalar_one())
    center_id = await _seed_collective(
        db_session,
        slug="broski-center",
        owner_id=center_owner,
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
    )
    await _seed_member(db_session, collective_id=center_id, trainer_id=trainer_id)

    memberships = await list_active_collective_memberships(db_session, trainer_id)
    assert len(memberships) == 2
    slugs = {m.slug for m in memberships}
    assert slugs == {"broski-center", "ice-studio"}

    ice = await resolve_collective_membership(db_session, trainer_id, collective_slug="ice-studio")
    assert ice is not None and ice.slug == "ice-studio" and ice.role == MEMBER_ROLE_OWNER

    center = await resolve_collective_membership(db_session, trainer_id, collective_slug="broski-center")
    assert center is not None and center.slug == "broski-center" and center.role == MEMBER_ROLE_MEMBER


@pytest.mark.asyncio
async def test_bootstrap_payload_lists_all_collectives(db_session) -> None:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    trainer_id = int(r.scalar_one())
    await _seed_collective(db_session, slug="alpha", owner_id=trainer_id)
    r_owner = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    other_owner = int(r_owner.scalar_one())
    beta_id = await _seed_collective(db_session, slug="beta", owner_id=other_owner)
    await _seed_member(db_session, collective_id=beta_id, trainer_id=trainer_id)

    memberships = await list_active_collective_memberships(db_session, trainer_id)
    payload = build_trainer_collective_bootstrap_payload(
        memberships[0],
        memberships=memberships,
    )
    assert payload is not None
    assert payload["has_multiple_memberships"] is True
    assert len(payload["collectives"]) == 2
    assert {c["slug"] for c in payload["collectives"]} == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_personal_slot_blocked_when_overlaps_center_duty(db_session) -> None:
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
    cid = await _seed_collective(
        db_session,
        slug="duty-block",
        owner_id=owner_id,
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
    )
    await _seed_member(db_session, collective_id=cid, trainer_id=coach_id)

    slot_date = date.today() + timedelta(days=4)
    created = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(10, 0),
        end_time=time(11, 0),
        coach_trainer_ids=[coach_id],
    )
    assert created and created.get("error") is None

    with pytest.raises(ValueError, match="дежурств"):
        await assert_no_center_duty_conflict_for_slots(
            db_session,
            trainer_id=coach_id,
            slot_date=slot_date,
            intervals=[(time(10, 30), time(11, 30))],
        )

    await assert_no_center_duty_conflict_for_slots(
        db_session,
        trainer_id=coach_id,
        slot_date=slot_date,
        intervals=[(time(12, 0), time(13, 0))],
    )
