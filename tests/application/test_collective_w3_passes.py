"""Collective ADR-003 W3: center pass products, issue, redeem on booking confirm."""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.collective_pass_use_cases import (
    PASS_KIND_COACH,
    PASS_KIND_LANE,
    compute_center_booking_price_with_pass,
    issue_collective_pass_to_client,
    list_client_collective_passes,
    pass_credits_for_attendance_mode,
    redeem_collective_pass_for_session_booking,
    seed_reference_collective_pass_products,
)
from src.application.collective_session_use_cases import (
    ATTENDANCE_COACH_PAIR,
    ATTENDANCE_LANE_SELF,
    ATTENDANCE_LANE_WITH_GUEST,
    CENTER_TARIFF_GUEST_SURCHARGE_CENTS,
    confirm_collective_session_booking,
    create_collective_session,
    create_collective_session_booking,
)
from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    SCHEDULE_MODE_STUDIO_CENTRAL,
)

pytestmark = pytest.mark.collective


async def _seed_studio_central(db_session, *, slug: str = "throw-center-w3") -> tuple[int, int]:
    now = datetime.now(timezone.utc)
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
            VALUES (:slug, 'Throw Center W3', :st, 5, :oid, :mode, :now, :now)
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


async def _seed_client(db_session, telegram_id: int = 910001) -> int:
    r = await db_session.execute(
        text("INSERT INTO clients (telegram_id, created_at) VALUES (:tid, NOW()) RETURNING id"),
        {"tid": telegram_id},
    )
    client_id = int(r.scalar_one())
    await db_session.commit()
    return client_id


@pytest.mark.asyncio
async def test_compute_price_with_lane_pass_guest_surcharge_only() -> None:
    assert compute_center_booking_price_with_pass(
        ATTENDANCE_LANE_SELF,
        using_pass=True,
        pass_kind=PASS_KIND_LANE,
    ) == 0
    assert compute_center_booking_price_with_pass(
        ATTENDANCE_LANE_WITH_GUEST,
        guest_count=2,
        using_pass=True,
        pass_kind=PASS_KIND_LANE,
    ) == 2 * CENTER_TARIFF_GUEST_SURCHARGE_CENTS


@pytest.mark.asyncio
async def test_seed_issue_and_redeem_lane_pass_on_confirm(db_session) -> None:
    cid, owner_id = await _seed_studio_central(db_session)
    client_id = await _seed_client(db_session)

    seeded = await seed_reference_collective_pass_products(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
    )
    assert seeded.get("created") == 6
    lane_product = next(p for p in seeded["products"] if p["pass_kind"] == PASS_KIND_LANE and p["sessions_total"] == 4)

    issued = await issue_collective_pass_to_client(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        client_id=client_id,
        collective_pass_product_id=int(lane_product["id"]),
    )
    assert issued.get("error") is None
    inst_id = int(issued["id"])

    slot_date = date.today() + timedelta(days=5)
    created = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(10, 0),
        end_time=time(11, 0),
    )
    session_id = int(created["id"])

    booking = await create_collective_session_booking(
        db_session,
        session_id=session_id,
        client_id=client_id,
        attendance_mode=ATTENDANCE_LANE_SELF,
        collective_pass_instance_id=inst_id,
    )
    assert booking and booking.get("error") is None
    assert booking["booking_price_cents"] == 0
    assert booking["pass_credits_reserved"] == 1
    assert booking["status"] == "pending"

    r_pass = await db_session.execute(
        text("SELECT sessions_remaining FROM collective_pass_instances WHERE id = :id"),
        {"id": inst_id},
    )
    assert int(r_pass.scalar_one()) == 4

    confirmed = await confirm_collective_session_booking(
        db_session,
        booking_id=int(booking["booking_id"]),
        trainer_id=owner_id,
    )
    assert confirmed and confirmed.get("ok")

    redeemed = await redeem_collective_pass_for_session_booking(
        db_session,
        booking_id=int(booking["booking_id"]),
    )
    assert redeemed is True

    r_pass2 = await db_session.execute(
        text("SELECT sessions_remaining FROM collective_pass_instances WHERE id = :id"),
        {"id": inst_id},
    )
    assert int(r_pass2.scalar_one()) == 3

    passes = await list_client_collective_passes(
        db_session,
        client_id=client_id,
        collective_id=cid,
        redeemable_only=True,
    )
    assert len(passes) == 1
    assert passes[0]["sessions_remaining"] == 3


@pytest.mark.asyncio
async def test_pass_kind_mismatch_rejected(db_session) -> None:
    cid, owner_id = await _seed_studio_central(db_session, slug="w3-mismatch")
    client_id = await _seed_client(db_session, 910002)

    seeded = await seed_reference_collective_pass_products(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
    )
    lane_product = next(p for p in seeded["products"] if p["pass_kind"] == PASS_KIND_LANE)

    issued = await issue_collective_pass_to_client(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        client_id=client_id,
        collective_pass_product_id=int(lane_product["id"]),
    )
    inst_id = int(issued["id"])

    slot_date = date.today() + timedelta(days=6)
    created = await create_collective_session(
        db_session,
        collective_id=cid,
        owner_trainer_id=owner_id,
        slot_date=slot_date,
        start_time=time(11, 0),
        end_time=time(12, 0),
        coach_trainer_ids=[owner_id],
    )
    session_id = int(created["id"])

    bad = await create_collective_session_booking(
        db_session,
        session_id=session_id,
        client_id=client_id,
        attendance_mode=ATTENDANCE_COACH_PAIR,
        center_coach_id=owner_id,
        collective_pass_instance_id=inst_id,
    )
    assert bad and bad.get("error") == "pass_kind_mismatch"


@pytest.mark.asyncio
async def test_coach_pair_debits_two_credits(db_session) -> None:
    assert pass_credits_for_attendance_mode(ATTENDANCE_COACH_PAIR) == 2
