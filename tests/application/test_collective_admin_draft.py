"""Admin collective draft: org format presets + claim owner access mode."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    COLLECTIVE_STATUS_DRAFT,
    MEMBER_ROLE_MEMBER,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    ORG_FORMAT_CENTER,
    ORG_FORMAT_CENTER_HYBRID,
    ORG_FORMAT_STUDIO,
    SCHEDULE_MODE_STUDIO_CENTRAL,
    STUDIO_ACCESS_MODE_ADMIN_ONLY,
    STUDIO_ACCESS_MODE_FULL,
    consume_collective_claim_token,
    create_collective_draft,
    issue_collective_claim_token,
    parse_admin_collective_draft_body,
)

pytestmark = pytest.mark.collective


class TestParseAdminCollectiveDraftBody:
    def test_minimal_defaults_to_studio(self) -> None:
        spec = parse_admin_collective_draft_body("ice-yoga|Ice Yoga Lane")
        assert isinstance(spec, object)
        assert spec.slug == "ice-yoga"
        assert spec.organization_format == ORG_FORMAT_STUDIO
        assert spec.schedule_mode == "member_autonomous"
        assert spec.seat_limit == 5
        assert spec.owner_studio_access_mode == STUDIO_ACCESS_MODE_FULL

    def test_center_hybrid_with_seats(self) -> None:
        spec = parse_admin_collective_draft_body("broski|Broski Center|center_hybrid|8")
        assert spec.organization_format == ORG_FORMAT_CENTER_HYBRID
        assert spec.schedule_mode == SCHEDULE_MODE_STUDIO_CENTRAL
        assert spec.seat_limit == 8
        assert spec.owner_studio_access_mode == STUDIO_ACCESS_MODE_FULL

    def test_center_hybrid_via_legacy_center_alias_and_trainer_owner(self) -> None:
        spec = parse_admin_collective_draft_body("broski|Broski Center|center|8|trainer")
        assert spec.organization_format == ORG_FORMAT_CENTER_HYBRID
        assert spec.schedule_mode == SCHEDULE_MODE_STUDIO_CENTRAL
        assert spec.owner_studio_access_mode == STUDIO_ACCESS_MODE_FULL

    def test_center_preset_sets_admin_only_owner(self) -> None:
        spec = parse_admin_collective_draft_body("ops|Ops Desk|center")
        assert spec.organization_format == ORG_FORMAT_CENTER
        assert spec.schedule_mode == SCHEDULE_MODE_STUDIO_CENTRAL
        assert spec.owner_studio_access_mode == STUDIO_ACCESS_MODE_ADMIN_ONLY

    def test_manager_alias_maps_to_center(self) -> None:
        spec = parse_admin_collective_draft_body("ops|Ops Desk|manager")
        assert spec.organization_format == ORG_FORMAT_CENTER
        assert spec.owner_studio_access_mode == STUDIO_ACCESS_MODE_ADMIN_ONLY

    def test_coworking_alias_maps_to_studio(self) -> None:
        spec = parse_admin_collective_draft_body("fit|Fit Hub|coworking|12")
        assert spec.organization_format == ORG_FORMAT_STUDIO
        assert spec.seat_limit == 12

    def test_invalid_format(self) -> None:
        assert parse_admin_collective_draft_body("x|Name|unknown") == "invalid_format"

    def test_invalid_seats(self) -> None:
        assert parse_admin_collective_draft_body("x|Name|studio|999") == "invalid_seats"

    def test_studio_rejects_admin_only_owner(self) -> None:
        assert parse_admin_collective_draft_body("x|Name|studio|5|manager") == "invalid_owner_mode"


@pytest.mark.asyncio
async def test_create_collective_draft_persists_org_profile(db_session) -> None:
    created = await create_collective_draft(
        db_session,
        slug="draft-center",
        display_name="Draft Center",
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
        owner_studio_access_mode=STUDIO_ACCESS_MODE_ADMIN_ONLY,
        organization_format=ORG_FORMAT_CENTER,
        seat_limit=7,
    )
    assert created["schedule_mode"] == SCHEDULE_MODE_STUDIO_CENTRAL
    assert created["owner_studio_access_mode"] == STUDIO_ACCESS_MODE_ADMIN_ONLY
    assert created["organization_format"] == ORG_FORMAT_CENTER
    assert created["seat_limit"] == 7

    r = await db_session.execute(
        text(
            """
            SELECT schedule_mode, owner_studio_access_mode, organization_format, seat_limit, status
            FROM collectives WHERE slug = :slug
            """
        ),
        {"slug": "draft-center"},
    )
    row = r.fetchone()
    assert row is not None
    assert row[0] == SCHEDULE_MODE_STUDIO_CENTRAL
    assert row[1] == STUDIO_ACCESS_MODE_ADMIN_ONLY
    assert row[2] == ORG_FORMAT_CENTER
    assert int(row[3]) == 7
    assert row[4] == COLLECTIVE_STATUS_DRAFT


@pytest.mark.asyncio
async def test_get_collective_ops_status_draft_with_claim(db_session) -> None:
    from src.application.collective_use_cases import get_collective_ops_status

    created = await create_collective_draft(
        db_session,
        slug="ops-status",
        display_name="Ops Status Studio",
        organization_format=ORG_FORMAT_CENTER,
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
        owner_studio_access_mode=STUDIO_ACCESS_MODE_ADMIN_ONLY,
        seat_limit=6,
    )
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    assert claim is not None

    ops = await get_collective_ops_status(db_session, slug="ops-status")
    assert ops is not None
    assert ops["status"] == COLLECTIVE_STATUS_DRAFT
    assert ops["organization_format"] == ORG_FORMAT_CENTER
    assert ops["owner_studio_access_mode"] == STUDIO_ACCESS_MODE_ADMIN_ONLY
    assert ops["pending_claim_count"] >= 1
    assert "claim link outstanding" in ops["claim_state_label"]
    assert ops["owner_trainer_id"] is None


@pytest.mark.asyncio
async def test_suspended_collective_notice_for_member(db_session) -> None:
    from src.application.collective_use_cases import (
        COLLECTIVE_STATUS_SUSPENDED,
        get_trainer_suspended_collective_notice,
    )

    now = datetime.now(timezone.utc)
    r_tr = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    trainer_id = int(r_tr.scalar_one())
    created = await create_collective_draft(
        db_session,
        slug="suspended-studio",
        display_name="Suspended Studio",
    )
    cid = int(created["id"])
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :role, :active, :now)
            """
        ),
        {
            "cid": cid,
            "tid": trainer_id,
            "role": MEMBER_ROLE_MEMBER,
            "active": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await db_session.execute(
        text("UPDATE collectives SET status = :st WHERE id = :cid"),
        {"st": COLLECTIVE_STATUS_SUSPENDED, "cid": cid},
    )
    await db_session.commit()

    notice = await get_trainer_suspended_collective_notice(db_session, trainer_id)
    assert notice is not None
    assert notice["slug"] == "suspended-studio"
    assert "приостановлена" in notice["message"]


@pytest.mark.asyncio
async def test_claim_applies_owner_studio_access_mode(db_session) -> None:
    now = datetime.now(timezone.utc)
    r_tr = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    trainer_id = int(r_tr.scalar_one())

    created = await create_collective_draft(
        db_session,
        slug="claim-manager",
        display_name="Claim Manager",
        organization_format=ORG_FORMAT_CENTER,
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
        owner_studio_access_mode=STUDIO_ACCESS_MODE_ADMIN_ONLY,
    )
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    assert claim is not None

    result = await consume_collective_claim_token(db_session, claim["token"], trainer_id)
    assert result.error is None

    r_mode = await db_session.execute(
        text("SELECT studio_access_mode FROM trainers WHERE id = :tid"),
        {"tid": trainer_id},
    )
    assert r_mode.scalar_one() == STUDIO_ACCESS_MODE_ADMIN_ONLY

    r_col = await db_session.execute(
        text("SELECT status, owner_trainer_id FROM collectives WHERE slug = :slug"),
        {"slug": "claim-manager"},
    )
    col = r_col.fetchone()
    assert col is not None
    assert col[0] == COLLECTIVE_STATUS_ACTIVE
    assert int(col[1]) == trainer_id

    r_mem = await db_session.execute(
        text(
            """
            SELECT role, status FROM collective_members
            WHERE collective_id = :cid AND trainer_id = :tid
            """
        ),
        {"cid": int(created["id"]), "tid": trainer_id},
    )
    mem = r_mem.fetchone()
    assert mem is not None
    assert mem[0] == MEMBER_ROLE_OWNER
    assert mem[1] == MEMBER_STATUS_ACTIVE
