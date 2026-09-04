"""
TASK-043 AC-004: bePaid checkout currency follows the trainer's city (BYN for BY, RUB for RU),
instead of the previous hardcoded "BYN".
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal


def _fresh_trainer_telegram_id() -> int:
    return 5_200_000_000 + (uuid.uuid4().int % 3_000_000_000)


async def _insert_subscription_plan(session: AsyncSession) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO subscription_plans (name, price_cents, period_days, is_trial, sort_order)
            VALUES ('CurrencyTestPlan', 9900, 30, false, 0)
            RETURNING id
            """
        )
    )
    return int(r.scalar_one())


async def _insert_city(db_session: AsyncSession, *, country: str) -> int:
    price_group = "RU_BASE" if country == "RU" else "BY_BASE"
    r = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group)
            VALUES (:name, :country, :price_group)
            RETURNING id
            """
        ),
        {"name": f"CurrencyTest-{uuid.uuid4().hex[:8]}", "country": country, "price_group": price_group},
    )
    return int(r.scalar_one())


async def _make_trainer(db_session: AsyncSession, *, city_id: int | None) -> tuple[int, int]:
    create_resp_trainer_id: int
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Currency", "last_name": "Test", "age": 30}},
        )
        assert create_resp.status_code == 200, create_resp.text
        create_resp_trainer_id = int(create_resp.json()["id"])

    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg, status = 'active' WHERE id = :id"),
        {"tg": tg, "id": create_resp_trainer_id},
    )
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_id, "tid": create_resp_trainer_id},
    )
    await db_session.commit()
    return create_resp_trainer_id, tg


@pytest.mark.asyncio
async def test_subscription_payment_url_uses_rub_for_ru_city_trainer(
    app_use_test_db,
    db_session: AsyncSession,
) -> None:
    ru_city_id = await _insert_city(db_session, country="RU")
    await _insert_subscription_plan(db_session)
    trainer_id, tg = await _make_trainer(db_session, city_id=ru_city_id)

    captured: dict = {}

    async def _fake_create_checkout(**kwargs):
        captured.update(kwargs)
        return {"payment_url": "https://example.test/stub", "transaction_id": None}

    with (
        patch(
            "src.api.miniapp_auth.deps.verify_telegram_init_data_principal",
            return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg),
        ),
        patch("src.api.routes.webapp.create_checkout", side_effect=_fake_create_checkout),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/subscription-payment-url",
                headers={"X-Telegram-Init-Data": "mock"},
            )

    assert resp.status_code == 200, resp.text
    assert captured.get("currency") == "RUB", captured


@pytest.mark.asyncio
async def test_subscription_payment_url_uses_byn_for_by_city_trainer(
    app_use_test_db,
    db_session: AsyncSession,
) -> None:
    by_city_id = await _insert_city(db_session, country="BY")
    await _insert_subscription_plan(db_session)
    trainer_id, tg = await _make_trainer(db_session, city_id=by_city_id)

    captured: dict = {}

    async def _fake_create_checkout(**kwargs):
        captured.update(kwargs)
        return {"payment_url": "https://example.test/stub", "transaction_id": None}

    with (
        patch(
            "src.api.miniapp_auth.deps.verify_telegram_init_data_principal",
            return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg),
        ),
        patch("src.api.routes.webapp.create_checkout", side_effect=_fake_create_checkout),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/subscription-payment-url",
                headers={"X-Telegram-Init-Data": "mock"},
            )

    assert resp.status_code == 200, resp.text
    assert captured.get("currency") == "BYN", captured


@pytest.mark.asyncio
async def test_subscription_payment_url_defaults_to_byn_without_city(
    app_use_test_db,
    db_session: AsyncSession,
) -> None:
    """Trainer with no city set yet (onboarding in progress) keeps today's BYN behavior."""
    await _insert_subscription_plan(db_session)
    trainer_id, tg = await _make_trainer(db_session, city_id=None)

    captured: dict = {}

    async def _fake_create_checkout(**kwargs):
        captured.update(kwargs)
        return {"payment_url": "https://example.test/stub", "transaction_id": None}

    with (
        patch(
            "src.api.miniapp_auth.deps.verify_telegram_init_data_principal",
            return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg),
        ),
        patch("src.api.routes.webapp.create_checkout", side_effect=_fake_create_checkout),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/subscription-payment-url",
                headers={"X-Telegram-Init-Data": "mock"},
            )

    assert resp.status_code == 200, resp.text
    assert captured.get("currency") == "BYN", captured
