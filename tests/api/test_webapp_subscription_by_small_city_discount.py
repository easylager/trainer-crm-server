"""
TASK-045: trainers from non-capital BY cities (price_group='BY_SMALL') get -15% pricing;
Minsk/oblast-capital trainers keep the unchanged BY_BASE price.
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
    return 5_400_000_000 + (uuid.uuid4().int % 3_000_000_000)


async def _insert_city(db_session: AsyncSession, *, name: str, price_group: str) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group)
            VALUES (:name, 'BY', :price_group)
            RETURNING id
            """
        ),
        {"name": name, "price_group": price_group},
    )
    return int(r.scalar_one())


async def _make_trainer(db_session: AsyncSession, *, city_id: int) -> int:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "SmallCity", "last_name": "Test", "age": 30}},
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
    return tg


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
    return int(catalog["constructor"]["base"]["prices_by_period"]["1"])


@pytest.mark.asyncio
async def test_catalog_discounted_for_small_by_city(app_use_test_db, db_session: AsyncSession) -> None:
    city_id = await _insert_city(db_session, name=f"Бобруйск-test-{uuid.uuid4().hex[:6]}", price_group="BY_SMALL")
    tg = await _make_trainer(db_session, city_id=city_id)
    catalog = await _get_catalog(tg)
    assert catalog["constructor"]["base"]["currency"] == "BYN"
    assert _crm_monthly_cents(catalog) == 1700  # 2000 * 0.85


@pytest.mark.asyncio
async def test_catalog_unchanged_for_capital_city(app_use_test_db, db_session: AsyncSession) -> None:
    city_id = await _insert_city(db_session, name=f"Минск-test-{uuid.uuid4().hex[:6]}", price_group="BY_BASE")
    tg = await _make_trainer(db_session, city_id=city_id)
    catalog = await _get_catalog(tg)
    assert catalog["constructor"]["base"]["currency"] == "BYN"
    assert _crm_monthly_cents(catalog) == 2000  # unchanged


@pytest.mark.asyncio
async def test_migration_capital_cities_stayed_by_base(db_session: AsyncSession) -> None:
    """Regression: the 0191 migration must not have touched Minsk/oblast-capital price_group."""
    r = await db_session.execute(
        text("SELECT name, price_group FROM cities WHERE country = 'BY' AND price_group != 'BY_BASE'")
    )
    rows = r.fetchall()
    capitals = {"Минск", "Гродно", "Брест", "Витебск", "Гомель", "Могилев"}
    for name, price_group in rows:
        assert name not in capitals, f"{name} should stay BY_BASE, got {price_group}"
