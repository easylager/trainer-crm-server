"""Collective Wave P1.5-A/B: admin subscription grant + owner brand edit."""
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.collective
from sqlalchemy import text

from src.application.collective_use_cases import (
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    COLLECTIVE_STATUS_ACTIVE,
    admin_grant_collective_subscription,
    get_collective_entitlements_for_member,
    get_collective_subscription_status,
    update_collective_brand,
    _infer_collective_subscription_tier,
)


def _mods(**kwargs: bool) -> dict[str, bool]:
    base = {"online": False, "analytics": False, "groups": False}
    base.update(kwargs)
    return base


class TestInferCollectiveSubscriptionTier:
    def test_analytics_when_analytics_module(self) -> None:
        assert _infer_collective_subscription_tier(_mods(analytics=True)) == "analytics"

    def test_online_without_analytics(self) -> None:
        assert _infer_collective_subscription_tier(_mods(online=True)) == "online"

    def test_crm_base_only(self) -> None:
        assert _infer_collective_subscription_tier(_mods()) == "crm"


@pytest.mark.asyncio
async def test_admin_grant_and_entitlements_merge(db_session) -> None:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, status, seat_limit, created_at, updated_at)
            VALUES ('p15-test-studio', 'P15 Studio', :st, 5, :now, :now)
            RETURNING id
            """
        ),
        {"st": COLLECTIVE_STATUS_ACTIVE, "now": now},
    )
    cid = int(r.scalar_one())
    r_tr = await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, created_at)
            VALUES ('active', :now)
            RETURNING id
            """
        ),
        {"now": now},
    )
    tid = int(r_tr.scalar_one())
    await db_session.execute(
        text(
            """
            UPDATE collectives SET owner_trainer_id = :tid WHERE id = :cid
            """
        ),
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

    granted = await admin_grant_collective_subscription(
        db_session,
        slug="p15-test-studio",
        period_months=3,
        modules=_mods(online=True, analytics=True, groups=True),
        admin_id=1,
    )
    assert granted is not None
    assert granted["slug"] == "p15-test-studio"
    assert "expires_at" in granted

    status = await get_collective_subscription_status(db_session, slug="p15-test-studio")
    assert status is not None
    assert status["active_subscription"] is not None

    ent = await get_collective_entitlements_for_member(db_session, tid)
    assert ent is not None
    assert ent.has_base_crm is True
    assert ent.modules.get("online") is True
    assert ent.modules.get("analytics") is True
    assert ent.modules.get("groups") is True


@pytest.mark.asyncio
async def test_owner_update_collective_brand(db_session) -> None:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, tagline, status, seat_limit, created_at, updated_at)
            VALUES ('p15-brand', 'Old Name', 'Old tag', :st, 5, :now, :now)
            RETURNING id
            """
        ),
        {"st": COLLECTIVE_STATUS_ACTIVE, "now": now},
    )
    cid = int(r.scalar_one())
    r_tr = await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, created_at)
            VALUES ('active', :now)
            RETURNING id
            """
        ),
        {"now": now},
    )
    tid = int(r_tr.scalar_one())
    await db_session.execute(
        text("UPDATE collectives SET owner_trainer_id = :tid WHERE id = :cid"),
        {"tid": tid, "cid": cid},
    )
    await db_session.commit()

    denied = await update_collective_brand(
        db_session,
        collective_id=cid,
        trainer_id=tid + 999,
        display_name="Nope",
    )
    assert denied == {"error": "not_owner"}

    updated = await update_collective_brand(
        db_session,
        collective_id=cid,
        trainer_id=tid,
        display_name="New Studio Name",
        tagline="Fresh tagline",
    )
    assert updated is not None
    assert updated["display_name"] == "New Studio Name"
    assert updated["tagline"] == "Fresh tagline"
    assert updated["slug"] == "p15-brand"
