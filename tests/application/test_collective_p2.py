"""Collective Wave P2: subscription pool UI payload + certificate white-label brand."""
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.collective
from sqlalchemy import text

from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    admin_grant_collective_subscription,
    format_collective_modules_list_ru,
    get_trainer_collective_studio_payload,
    resolve_certificate_brand_for_trainer,
    studio_subscription_pool_payload,
)


def test_format_collective_modules_list_ru() -> None:
    labels = format_collective_modules_list_ru(
        {"online": True, "analytics": True, "groups": False}
    )
    assert labels[0] == "CRM"
    assert "Онлайн-запись" in labels
    assert "Аналитика" in labels


def test_studio_subscription_pool_payload_active() -> None:
    payload = studio_subscription_pool_payload(
        {
            "seat_limit": 5,
            "active_member_count": 2,
            "active_subscription": {
                "expires_at": "2026-09-01T00:00:00+00:00",
                "modules": {"online": True},
                "tier": "online",
            },
        }
    )
    assert payload["active"] is True
    assert payload["expires_date"] == "2026-09-01"
    assert payload["seats_label"] == "2 / 5 мест"
    assert "Онлайн-запись" in payload["modules"]


@pytest.mark.asyncio
async def test_resolve_certificate_brand_uses_studio_name(db_session) -> None:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, tagline, status, seat_limit, created_at, updated_at)
            VALUES ('cert-brand', 'Yoga Lane', 'Йога в центре', :st, 5, :now, :now)
            RETURNING id
            """
        ),
        {"st": COLLECTIVE_STATUS_ACTIVE, "now": now},
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
        {"cid": cid, "tid": tid, "role": MEMBER_ROLE_OWNER, "active": MEMBER_STATUS_ACTIVE, "now": now},
    )
    await db_session.commit()

    brand = await resolve_certificate_brand_for_trainer(db_session, tid)
    assert brand["display_name"] == "Yoga Lane"
    assert brand["tagline"] == "Йога в центре"
    assert brand["powered_by"]


@pytest.mark.asyncio
async def test_studio_payload_includes_subscription_pool(db_session) -> None:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, status, seat_limit, created_at, updated_at)
            VALUES ('pool-ui', 'Pool UI', :st, 5, :now, :now)
            RETURNING id
            """
        ),
        {"st": COLLECTIVE_STATUS_ACTIVE, "now": now},
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
            VALUES (:cid, :tid, 'owner', 'active', :now)
            """
        ),
        {"cid": cid, "tid": tid, "now": now},
    )
    await db_session.commit()

    await admin_grant_collective_subscription(
        db_session,
        slug="pool-ui",
        period_months=1,
        admin_id=1,
    )

    payload = await get_trainer_collective_studio_payload(db_session, tid)
    assert payload is not None
    pool = payload.get("subscription_pool") or {}
    assert pool.get("active") is True
    assert pool.get("expires_date")
    assert pool.get("modules")
