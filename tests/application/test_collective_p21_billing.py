"""Collective Wave P2.1: self-service pool subscription billing."""
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.collective
from sqlalchemy import text

from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    admin_confirm_collective_invoice,
    compute_collective_subscription_price_cents,
    confirm_collective_invoice_after_payment,
    create_collective_subscription_invoice,
    get_collective_subscription_status,
    get_trainer_collective_studio_payload,
)


def test_compute_collective_subscription_price_cents() -> None:
    assert compute_collective_subscription_price_cents(5, 1, cents_per_seat_month=2900) == 14500
    assert compute_collective_subscription_price_cents(5, 3, cents_per_seat_month=2900) == 43500


async def _seed_owner_studio(db_session, *, slug: str = "bill-studio", seats: int = 5) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, status, seat_limit, created_at, updated_at)
            VALUES (:slug, 'Bill Studio', :st, :seats, :now, :now)
            RETURNING id
            """
        ),
        {"slug": slug, "st": COLLECTIVE_STATUS_ACTIVE, "seats": seats, "now": now},
    )
    cid = int(r.scalar_one())
    r_tr = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    tid = int(r_tr.scalar_one())
    await db_session.execute(
        text("UPDATE collectives SET owner_trainer_id = :tid WHERE id = :cid"),
        {"tid": tid, "cid": cid},
    )
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
            "role": MEMBER_ROLE_OWNER,
            "active": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await db_session.commit()
    return cid, tid


@pytest.mark.asyncio
async def test_create_and_confirm_collective_invoice(db_session) -> None:
    cid, tid = await _seed_owner_studio(db_session, slug="bill-confirm")

    inv = await create_collective_subscription_invoice(
        db_session,
        collective_id=cid,
        requested_by_trainer_id=tid,
        period_months=1,
    )
    assert inv is not None
    assert inv.get("error") is None
    assert inv["amount_cents"] == compute_collective_subscription_price_cents(5, 1)
    invoice_id = int(inv["invoice_id"])

    ok = await confirm_collective_invoice_after_payment(
        db_session, invoice_id, "test-payment-1"
    )
    assert ok is True

    status = await get_collective_subscription_status(db_session, collective_id=cid)
    assert status is not None
    assert status.get("active_subscription") is not None


@pytest.mark.asyncio
async def test_studio_payload_includes_subscription_checkout(db_session) -> None:
    cid, tid = await _seed_owner_studio(db_session, slug="bill-ui")

    payload = await get_trainer_collective_studio_payload(db_session, tid)
    assert payload is not None
    checkout = payload.get("subscription_checkout") or {}
    assert checkout.get("checkout_mode")
    assert len(checkout.get("pricing") or []) == 3
    assert checkout["pricing"][0]["amount_cents"] > 0


@pytest.mark.asyncio
async def test_create_invoice_rejects_non_owner(db_session) -> None:
    cid, owner_tid = await _seed_owner_studio(db_session, slug="bill-owner")
    now = datetime.now(timezone.utc)
    r_tr = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    other_tid = int(r_tr.scalar_one())
    await db_session.commit()

    inv = await create_collective_subscription_invoice(
        db_session,
        collective_id=cid,
        requested_by_trainer_id=other_tid,
        period_months=1,
    )
    assert inv is not None
    assert inv.get("error") == "not_owner"


@pytest.mark.asyncio
async def test_admin_confirm_collective_invoice(db_session) -> None:
    cid, tid = await _seed_owner_studio(db_session, slug="bill-admin")

    inv = await create_collective_subscription_invoice(
        db_session,
        collective_id=cid,
        requested_by_trainer_id=tid,
        period_months=1,
    )
    assert inv is not None
    invoice_id = int(inv["invoice_id"])

    result = await admin_confirm_collective_invoice(db_session, invoice_id, admin_id=999)
    assert result is not None
    assert result["invoice_id"] == invoice_id

    status = await get_collective_subscription_status(db_session, collective_id=cid)
    assert status is not None
    assert status.get("active_subscription") is not None

    # Idempotent second confirm
    again = await admin_confirm_collective_invoice(db_session, invoice_id, admin_id=999)
    assert again is not None
