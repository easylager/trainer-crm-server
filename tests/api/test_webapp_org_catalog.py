"""TASK-141 (S5): org catalog screen + publish/hide, and the public-endpoint gate they control.

Self-serve — no moderator (owner decision). Publish is blocked while the profile checklist
is open; the public landing page (``/api/public/collectives/{slug}``) only serves a
``published`` school.
"""
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


async def _claim_school(db_session, *, slug: str, telegram_id: int) -> int:
    created = await create_collective_draft(db_session, slug=slug, display_name=slug)
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    outcome = await consume_collective_claim_token_for_operator(db_session, claim["token"], telegram_id)
    assert outcome.error is None
    return int(created["id"])


@pytest.mark.asyncio
async def test_catalog_get_shows_draft_and_blocks_publish(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_400_001
    await _claim_school(db_session, slug="org-cat-fresh", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/webapp/org/catalog", headers={"X-Telegram-Init-Data": "mock"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "draft"
    assert body["can_publish"] is False
    assert body["readiness"]["ready"] is False
    assert body["public_url"] is None


@pytest.mark.asyncio
async def test_catalog_publish_blocked_until_checklist_ready(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_400_002
    await _claim_school(db_session, slug="org-cat-blocked", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/catalog/publish", headers={"X-Telegram-Init-Data": "mock"}
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_catalog_publish_then_public_endpoint_then_hide(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_400_003
    slug = "org-cat-publish-flow"
    await _claim_school(db_session, slug=slug, telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Fill the checklist the same way S3's profile screen does.
            patch_resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "about": "Небольшая школа фигурного катания.",
                    "contacts": {"phone": "+375291234567"},
                },
            )
            assert patch_resp.status_code == 200

            publish_resp = await client.post(
                "/api/webapp/org/catalog/publish", headers={"X-Telegram-Init-Data": "mock"}
            )
            assert publish_resp.status_code == 200
            body = publish_resp.json()
            assert body["state"] == "published"
            assert body["public_url"] == f"/api/public/collectives/{slug}"

    # The collective isn't ``status=active`` yet (claim leaves it in draft account status
    # separate from catalog_state) — but the school is active from S1's claim onward in
    # this flow (consume_collective_claim_token_for_operator activates it). Public endpoint
    # should now serve it.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        public_resp = await client.get(f"/api/public/collectives/{slug}")
    assert public_resp.status_code == 200

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            hide_resp = await client.post(
                "/api/webapp/org/catalog/hide", headers={"X-Telegram-Init-Data": "mock"}
            )
    assert hide_resp.status_code == 200
    assert hide_resp.json()["state"] == "hidden"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        public_resp_after_hide = await client.get(f"/api/public/collectives/{slug}")
    assert public_resp_after_hide.status_code == 404


@pytest.mark.asyncio
async def test_catalog_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/org/catalog")
    assert resp.status_code == 401
