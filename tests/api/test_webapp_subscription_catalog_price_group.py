"""
TASK-044: GET /api/webapp/trainer/subscription/catalog returns the trainer's
price_group pricing (BY_BASE / RU_BASE / RU_MOSCOW) instead of always BY_BASE.
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
    return 5_300_000_000 + (uuid.uuid4().int % 3_000_000_000)


async def _insert_city(db_session: AsyncSession, *, country: str, price_group: str) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group)
            VALUES (:name, :country, :price_group)
            RETURNING id
            """
        ),
        {"name": f"PGTest-{uuid.uuid4().hex[:8]}", "country": country, "price_group": price_group},
    )
    return int(r.scalar_one())


async def _make_trainer(db_session: AsyncSession, *, city_id: int | None) -> tuple[int, int]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "PriceGroup", "last_name": "Test", "age": 30}},
        )
        assert create_resp.status_code == 200, create_resp.text
        trainer_id = int(create_resp.json()["id"])

    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg, status = 'active' WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_id, "tid": trainer_id},
    )
    await db_session.commit()
    return trainer_id, tg


async def _get_catalog(tg: int) -> dict:
    with patch(
        "src.api.miniapp_auth.deps.verify_telegram_init_data_principal",
        return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/subscription/catalog",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _crm_monthly_cents(catalog: dict) -> int:
    base = catalog["constructor"]["base"]
    assert base["tier"] == "crm"
    return int(base["prices_by_period"]["1"])


@pytest.mark.asyncio
async def test_catalog_defaults_to_by_base_without_city(app_use_test_db, db_session: AsyncSession) -> None:
    trainer_id, tg = await _make_trainer(db_session, city_id=None)
    catalog = await _get_catalog(tg)
    assert catalog["constructor"]["base"]["currency"] == "BYN"
    assert _crm_monthly_cents(catalog) == 2000


@pytest.mark.asyncio
async def test_catalog_uses_ru_base_pricing_for_spb_city(app_use_test_db, db_session: AsyncSession) -> None:
    city_id = await _insert_city(db_session, country="RU", price_group="RU_BASE")
    trainer_id, tg = await _make_trainer(db_session, city_id=city_id)
    catalog = await _get_catalog(tg)
    assert catalog["constructor"]["base"]["currency"] == "RUB"
    assert _crm_monthly_cents(catalog) == 59000


@pytest.mark.asyncio
async def test_catalog_uses_ru_moscow_premium_pricing(app_use_test_db, db_session: AsyncSession) -> None:
    city_id = await _insert_city(db_session, country="RU", price_group="RU_MOSCOW")
    trainer_id, tg = await _make_trainer(db_session, city_id=city_id)
    catalog = await _get_catalog(tg)
    assert catalog["constructor"]["base"]["currency"] == "RUB"
    assert _crm_monthly_cents(catalog) == 75000  # RU_BASE 59000 * 1.25


@pytest.mark.asyncio
async def test_admin_editing_by_base_price_does_not_touch_ru_rows(
    app_use_test_db, db_session: AsyncSession
) -> None:
    """Regression: subscription_tier_pricing now has 3 rows per tier (BY_BASE/RU_BASE/
    RU_MOSCOW). Before TASK-044's fix, admin's UPDATE ... WHERE tier = :tier had no
    price_group filter and would have silently overwritten every price_group's row."""
    from src.application.subscription_tier_use_cases import update_subscription_tier_pricing

    before = await db_session.execute(
        text(
            "SELECT price_cents FROM subscription_tier_pricing WHERE tier = 'crm' AND price_group = 'RU_BASE'"
        )
    )
    ru_base_before = before.scalar_one()

    result = await update_subscription_tier_pricing(
        db_session, "crm", admin_telegram_id=1, period_prices={"1": 12345}
    )
    assert result is not None
    assert result["price_cents"] == 12345

    after = await db_session.execute(
        text(
            "SELECT price_cents FROM subscription_tier_pricing WHERE tier = 'crm' AND price_group = 'RU_BASE'"
        )
    )
    ru_base_after = after.scalar_one()
    assert ru_base_after == ru_base_before == 59000
