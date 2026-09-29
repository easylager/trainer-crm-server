"""TASK-141 (S1) AC: GET /api/webapp/org/bootstrap."""
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.collective_use_cases import (
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


@pytest.mark.asyncio
async def test_bootstrap_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/org/bootstrap")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bootstrap_404_for_valid_user_without_operator_row(app_use_test_db) -> None:
    with patch_org_webapp_init(8_555_000_111):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/org/bootstrap",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bootstrap_returns_collective_context_for_operator(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_000_222
    created = await create_collective_draft(
        db_session, slug="org-bootstrap-api", display_name="Bootstrap API School"
    )
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    outcome = await consume_collective_claim_token_for_operator(db_session, claim["token"], telegram_id)
    assert outcome.error is None

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/org/bootstrap",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "org-bootstrap-api"
    assert body["display_name"] == "Bootstrap API School"
    assert body["role"] == "owner"
    assert body["status"] == "active"
