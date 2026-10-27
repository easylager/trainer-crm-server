"""GET /trainer/access отдаёт валюту города тренера: BY → BYN, RU → RUB (экраны подписывают суммы по ней)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal


async def _access_currency(db_session, country: str) -> str:
    tg = 5_900_000_000 + (uuid.uuid4().int % 3_000_000_000)
    city_id = 99_000 + (uuid.uuid4().int % 900)
    await db_session.execute(
        text("INSERT INTO cities (id, name, country, is_active) VALUES (:i, :n, :c, true)"),
        {"i": city_id, "n": f"Мир-{country}-{city_id}", "c": country},
    )
    tid = (
        await db_session.execute(
            text("INSERT INTO trainers (status, telegram_id) VALUES ('pending_profile', :tg) RETURNING id"), {"tg": tg}
        )
    ).scalar_one()
    await db_session.execute(text("INSERT INTO trainer_profiles (trainer_id, city_id) VALUES (:t, :c)"), {"t": tid, "c": city_id})
    await db_session.commit()
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/webapp/trainer/access", headers={"X-Telegram-Init-Data": "mock"})
    assert r.status_code == 200, r.text
    return r.json()["currency"]


@pytest.mark.asyncio
async def test_a_russian_city_trainer_gets_rub(app_use_test_db, db_session) -> None:
    assert await _access_currency(db_session, "RU") == "RUB"


@pytest.mark.asyncio
async def test_a_belarusian_city_trainer_gets_byn(app_use_test_db, db_session) -> None:
    assert await _access_currency(db_session, "BY") == "BYN"
