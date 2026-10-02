"""TASK-141 (S4): GET /api/webapp/org/team + POST /api/webapp/org/team/invite.

Scope note (DEC-002): only viewing the roster + issuing invites in this pass —
no promote/remove. Pending invites are anonymous single-use links, not tied to
an identity until consumed, so they surface as a count, not fabricated rows.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.collective_use_cases import (
    consume_collective_claim_token_for_operator,
    consume_collective_invite_token,
    create_collective_draft,
    issue_collective_claim_token,
)

pytestmark = pytest.mark.collective


@contextmanager
def patch_org_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


async def _claim_school(db_session, *, slug: str, telegram_id: int) -> int:
    created = await create_collective_draft(db_session, slug=slug, display_name=slug)
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    outcome = await consume_collective_claim_token_for_operator(db_session, claim["token"], telegram_id)
    assert outcome.error is None
    return int(created["id"])


async def _create_trainer(db_session, telegram_id: int) -> int:
    from sqlalchemy import text

    r = await db_session.execute(
        text(
            "INSERT INTO trainers (status, telegram_id, studio_access_mode, created_at) "
            "VALUES ('active', :tgid, 'full_trainer', :now) RETURNING id"
        ),
        {"tgid": telegram_id, "now": datetime.now(timezone.utc)},
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_team_get_empty_roster_for_fresh_school(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_300_001
    await _claim_school(db_session, slug="org-team-fresh", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/webapp/org/team", headers={"X-Telegram-Init-Data": "mock"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["members"] == []
    assert body["active_count"] == 0
    assert body["pending_invites"] == 0
    assert body["role"] == "owner"


@pytest.mark.asyncio
async def test_team_invite_creates_link_and_shows_as_pending(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_300_002
    await _claim_school(db_session, slug="org-team-invite", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            invite_resp = await client.post(
                "/api/webapp/org/team/invite", headers={"X-Telegram-Init-Data": "mock"}
            )
            assert invite_resp.status_code == 200
            invite_body = invite_resp.json()
            assert invite_body["invite_link"]
            assert invite_body["start_payload"].startswith("col_inv_")

            team_resp = await client.get("/api/webapp/org/team", headers={"X-Telegram-Init-Data": "mock"})
    assert team_resp.status_code == 200
    assert team_resp.json()["pending_invites"] == 1


@pytest.mark.asyncio
async def test_team_invite_forbidden_for_non_owner_admin(app_use_test_db, db_session) -> None:
    # No promote-to-admin flow exists yet (DEC-002/EPIC5 O3.10 not built) — insert
    # the admin operator row directly, as an already-existing admin would look.
    from sqlalchemy import text

    owner_tgid = 8_555_300_003
    admin_tgid = 8_555_300_004
    collective_id = await _claim_school(db_session, slug="org-team-admin", telegram_id=owner_tgid)

    await db_session.execute(
        text(
            "INSERT INTO collective_operators (collective_id, telegram_id, role, status, created_at, updated_at) "
            "VALUES (:cid, :tgid, 'admin', 'active', now(), now())"
        ),
        {"cid": collective_id, "tgid": admin_tgid},
    )
    await db_session.commit()

    with patch_org_webapp_init(admin_tgid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/team/invite", headers={"X-Telegram-Init-Data": "mock"}
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_team_shows_active_member_after_invite_consumed(app_use_test_db, db_session) -> None:
    owner_tgid = 8_555_300_005
    coach_tgid = 8_555_300_006
    collective_id = await _claim_school(db_session, slug="org-team-joined", telegram_id=owner_tgid)

    with patch_org_webapp_init(owner_tgid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            invite_resp = await client.post(
                "/api/webapp/org/team/invite", headers={"X-Telegram-Init-Data": "mock"}
            )
    token = invite_resp.json()["invite_link"].rsplit("col_inv_", 1)[1]

    trainer_id = await _create_trainer(db_session, coach_tgid)
    result = await consume_collective_invite_token(db_session, token, trainer_id)
    assert result.error is None

    with patch_org_webapp_init(owner_tgid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            team_resp = await client.get("/api/webapp/org/team", headers={"X-Telegram-Init-Data": "mock"})
    body = team_resp.json()
    assert body["active_count"] == 1
    assert body["pending_invites"] == 0
    assert len(body["members"]) == 1
    assert body["members"][0]["trainer_id"] == trainer_id
    assert body["members"][0]["status"] == "active"
    assert body["collective_id"] == collective_id


@pytest.mark.asyncio
async def test_team_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/org/team")
    assert resp.status_code == 401
