"""Collective ADR-003 W2: studio_central sessions + PAYG bookings."""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.collective_session_use_cases import (
    ATTENDANCE_COACH_INDIVIDUAL,
    ATTENDANCE_LANE_SELF,
    ATTENDANCE_LANE_WITH_GUEST,
    CENTER_TARIFF_GUEST_SURCHARGE_CENTS,
    CENTER_TARIFF_LANE_HOUR_CENTS,
    compute_center_booking_price_cents,
    create_collective_session,
    create_collective_session_booking,
    duplicate_collective_sessions_week,
    list_collective_sessions_for_studio,
    list_public_collective_sessions,
)
from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_MEMBER,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    SCHEDULE_MODE_STUDIO_CENTRAL,
)

pytestmark = pytest.mark.collective


async def _seed_studio_central(
    db_session,
    *,
    slug: str = "throw-center",
    owner_id: int | None = None,
) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    if owner_id is None:
        r = await db_session.execute(
            text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
            {"now": now},
        )
        owner_id = int(r.scalar_one())
    r_col = await db_session.execute(
        text(
            """
            INSERT INTO collectives (
                slug, display_name, status, seat_limit, owner_trainer_id,
                schedule_mode, created_at, updated_at
            )
            VALUES (:slug, 'Throw Center', :st, 5, :oid, :mode, :now, :now)
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
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :role, :active, :now)
            """
        ),
        {
            "cid": cid,
            "tid": owner_id,
            "role": MEMBER_ROLE_OWNER,
            "active": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await db_session.commit()
    return cid, owner_id


@pytest.mark.asyncio
async def test_compute_center_booking_price_guest_surcharge() -> None:
    assert compute_center_booking_price_cents(ATTENDANCE_LANE_SELF) == CENTER_TARIFF_LANE_HOUR_CENTS
    assert compute_center_booking_price_cents(
        ATTENDANCE_LANE_WITH_GUEST,
        guest_count=2,
    ) == CENTER_TARIFF_LANE_HOUR_CENTS + 2 * CENTER_TARIFF_GUEST_SURCHARGE_CENTS


@pytest.mark.asyncio
async def test_create_session_and_book_lane_self(db_session) -> None:
    cid, owner_id = await _seed_studio_central(db_session)
    slot_date = date.today() + timedelta(days=3)
    created = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=2,
    )
    assert created is not None
    assert created.get("error") is None
    session_id = int(created["id"])

    r_client = await db_session.execute(
        text("INSERT INTO clients (telegram_id, created_at) VALUES (900001, NOW()) RETURNING id")
    )
    client_id = int(r_client.scalar_one())
    await db_session.commit()

    booking = await create_collective_session_booking(
        db_session,
        session_id=session_id,
        client_id=client_id,
        attendance_mode=ATTENDANCE_LANE_SELF,
    )
    assert booking is not None
    assert booking["status"] == "pending"
    assert booking["trainer_id"] == owner_id
    assert booking["booking_price_cents"] == CENTER_TARIFF_LANE_HOUR_CENTS


@pytest.mark.asyncio
async def test_booking_requires_assigned_coach(db_session) -> None:
    cid, owner_id = await _seed_studio_central(db_session, slug="coach-assign")
    now = datetime.now(timezone.utc)
    r_coach = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    coach_id = int(r_coach.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :role, :active, :now)
            """
        ),
        {
            "cid": cid,
            "tid": coach_id,
            "role": MEMBER_ROLE_MEMBER,
            "active": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await db_session.commit()

    slot_date = date.today() + timedelta(days=4)
    created = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(12, 0),
        end_time=time(13, 0),
        coach_trainer_ids=[coach_id],
    )
    session_id = int(created["id"])

    r_client = await db_session.execute(
        text("INSERT INTO clients (telegram_id, created_at) VALUES (900002, NOW()) RETURNING id")
    )
    client_id = int(r_client.scalar_one())
    await db_session.commit()

    bad = await create_collective_session_booking(
        db_session,
        session_id=session_id,
        client_id=client_id,
        attendance_mode=ATTENDANCE_COACH_INDIVIDUAL,
        center_coach_id=owner_id,
    )
    assert bad and bad.get("error") == "coach_not_assigned"

    ok = await create_collective_session_booking(
        db_session,
        session_id=session_id,
        client_id=client_id,
        attendance_mode=ATTENDANCE_COACH_INDIVIDUAL,
        center_coach_id=coach_id,
    )
    assert ok and ok.get("error") is None
    assert ok["trainer_id"] == coach_id


@pytest.mark.asyncio
async def test_create_session_without_coaches_allows_lane_booking(db_session) -> None:
    """Broski-style: lane window without duty coaches; coach required only for coach attendance modes."""
    cid, owner_id = await _seed_studio_central(db_session)
    slot_date = date.today() + timedelta(days=5)
    created = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(9, 0),
        end_time=time(10, 0),
        coach_trainer_ids=[],
    )
    assert created and created.get("error") is None
    assert created.get("assigned_coaches") == []
    session_id = int(created["id"])

    r_client = await db_session.execute(
        text("INSERT INTO clients (telegram_id, created_at) VALUES (900003, NOW()) RETURNING id")
    )
    client_id = int(r_client.scalar_one())
    await db_session.commit()

    ok = await create_collective_session_booking(
        db_session,
        session_id=session_id,
        client_id=client_id,
        attendance_mode=ATTENDANCE_LANE_SELF,
    )
    assert ok and ok.get("error") is None


@pytest.mark.asyncio
async def test_public_sessions_rejects_member_autonomous(db_session) -> None:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, status, seat_limit, created_at, updated_at)
            VALUES ('ice-studio', 'Ice', 'active', 5, :now, :now)
            RETURNING id
            """
        ),
        {"now": now},
    )
    assert r.scalar_one()
    await db_session.commit()
    payload = await list_public_collective_sessions(
        db_session,
        slug="ice-studio",
        from_date=date.today(),
        to_date=date.today() + timedelta(days=7),
    )
    assert payload and payload.get("error") == "not_studio_central"


@pytest.mark.asyncio
async def test_duplicate_collective_sessions_week(db_session) -> None:
    cid, owner_id = await _seed_studio_central(db_session, slug="dup-week")
    monday = date.today() - timedelta(days=date.today().weekday())
    wednesday = monday + timedelta(days=2)
    friday = monday + timedelta(days=4)

    for slot_date, start, end in (
        (wednesday, time(10, 0), time(11, 0)),
        (friday, time(18, 0), time(19, 30)),
    ):
        created = await create_collective_session(
            db_session,
            collective_id=cid,
            owner_trainer_id=owner_id,
            slot_date=slot_date,
            start_time=start,
            end_time=end,
            capacity=3,
        )
        assert created and not created.get("error")

    result = await duplicate_collective_sessions_week(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        source_week_start=wednesday,
        weeks_ahead=1,
    )
    assert result.get("error") is None
    assert result["created_count"] == 2
    assert result["skipped_count"] == 0

    dup = await duplicate_collective_sessions_week(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        source_week_start=monday,
        weeks_ahead=1,
    )
    assert dup["created_count"] == 0
    assert dup["skipped_count"] == 2

    target_monday = monday + timedelta(days=7)
    target_sunday = target_monday + timedelta(days=6)
    copied = await list_collective_sessions_for_studio(
        db_session,
        collective_id=cid,
        from_date=target_monday,
        to_date=target_sunday,
    )
    assert len(copied) == 2
