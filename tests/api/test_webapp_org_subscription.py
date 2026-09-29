"""TASK-141 (S2): GET /api/webapp/org/collective/subscription."""
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.collective_use_cases import (
    admin_grant_collective_subscription,
    consume_collective_claim_token_for_operator,
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


@pytest.mark.asyncio
async def test_subscription_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/org/collective/subscription")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_subscription_404_for_non_operator(app_use_test_db) -> None:
    with patch_org_webapp_init(8_555_100_001):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/org/collective/subscription",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_subscription_owner_sees_no_active_subscription_before_grant(
    app_use_test_db, db_session
) -> None:
    telegram_id = 8_555_100_002
    await _claim_school(db_session, slug="org-sub-no-grant", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/org/collective/subscription",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "owner"
    assert body["has_active_subscription"] is False
    assert body["active"] is None


@pytest.mark.asyncio
async def test_subscription_operator_sees_active_after_admin_grant(
    app_use_test_db, db_session
) -> None:
    telegram_id = 8_555_100_003
    await _claim_school(db_session, slug="org-sub-granted", telegram_id=telegram_id)
    await admin_grant_collective_subscription(
        db_session,
        slug="org-sub-granted",
        period_months=1,
        modules={"online": True, "analytics": False, "groups": False},
        admin_id=1,
    )

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/org/collective/subscription",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_active_subscription"] is True
    assert body["active"]["tier"] == "online"
