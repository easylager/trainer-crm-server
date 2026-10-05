"""POST /trainer/onboarding/city (TASK-170)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from tests.api.test_webapp_trainer_quick_setup import (
    QUICK_SETUP_URL,
    _any_service_id,
    _bare_linked_trainer,
    _fresh_trainer_telegram_id,
    patch_trainer_webapp_init,
)

CITY_URL = "/api/webapp/trainer/onboarding/city"


@pytest.mark.asyncio
async def test_onboarding_city_create_and_quick_setup_save(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)
    name = f"Онборд-Город-{uuid.uuid4().hex[:6]}"

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                CITY_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={"name": name},
            )
            assert created.status_code == 200, created.text
            body = created.json()
            assert body["status"] == "created"
            city_id = int(body["city_id"])

            saved = await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [],
                    "duration_minutes": 60,
                    "city_id": city_id,
                },
            )
            assert saved.status_code == 200, saved.text

            got = await client.get(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert got.status_code == 200
            cities = got.json().get("cities") or []
            match = [c for c in cities if int(c["id"]) == city_id]
            assert match, "creator must see pending city in list"
            assert match[0].get("is_active") is False

    prof = (
        await db_session.execute(
            text("SELECT city_id FROM trainer_profiles WHERE trainer_id = :t"),
            {"t": trainer_id},
        )
    ).fetchone()
    assert prof and int(prof[0]) == city_id
