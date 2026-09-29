"""TASK-141 (S3): GET/PATCH /api/webapp/org/profile — checklist onboarding."""
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
async def test_profile_get_shows_missing_required_fields(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_001
    await _claim_school(db_session, slug="org-profile-fresh", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/org/profile", headers={"X-Telegram-Init-Data": "mock"}
            )
    assert resp.status_code == 200
    body = resp.json()
    # display_name was set at draft creation, about/contact are not.
    assert body["readiness"]["ready"] is False
    assert "about" in body["readiness"]["missing"]
    assert "contact" in body["readiness"]["missing"]
    assert "display_name" not in body["readiness"]["missing"]


@pytest.mark.asyncio
async def test_profile_patch_fills_required_fields_and_becomes_ready(
    app_use_test_db, db_session
) -> None:
    telegram_id = 8_555_200_002
    await _claim_school(db_session, slug="org-profile-fill", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "about": "Небольшая школа фигурного катания для детей 4-12 лет.",
                    "contacts": {"phone": "+375291234567"},
                },
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["readiness"]["ready"] is True
    assert body["readiness"]["missing"] == []
    assert body["about"] == "Небольшая школа фигурного катания для детей 4-12 лет."
    assert body["contacts"]["phone"] == "+375291234567"


@pytest.mark.asyncio
async def test_profile_patch_rejects_empty_display_name(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_003
    await _claim_school(db_session, slug="org-profile-badname", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"display_name": "   "},
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_profile_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/org/profile")
    assert resp.status_code == 401
