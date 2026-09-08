"""TASK-055: hub teaser «Лёд рядом» + trainer arena chips (AC-001–004)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.arena_public_use_cases import get_hub_ice_teaser
from src.application.client_use_cases import get_or_create_client
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city
from tests.api.test_webapp_client_miniapp_integration import (
    _fresh_client_telegram_id,
    patch_client_init_auth,
)
from tests.conftest import belarus_test_phone

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ice_teaser_model_node_unit() -> None:
    """AC-001/002 + EDGE-002 copy and hide-if-empty."""
    proc = subprocess.run(
        ["node", "--test", "tests/js/ice-teaser-model.test.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_trainer_arena_chips_model_node_unit() -> None:
    """AC-003 + EDGE-001 chips, primary mark, overflow, slot place caption."""
    proc = subprocess.run(
        ["node", "--test", "tests/js/trainer-arena-chips-model.test.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.asyncio
async def test_hub_and_catalog_assets_include_ice_links(app_use_test_db) -> None:
    """Teaser and chips models are served; hub still has trainer / bookings / passes mounts."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        home = await client.get("/webapp/client-home")
        catalog = await client.get("/webapp/catalog?trainer_id=1")
        teaser_js = await client.get("/webapp/ice-teaser-model.js")
        chips_js = await client.get("/webapp/trainer-arena-chips-model.js")
        home_js = await client.get("/webapp/client-home-main.js")
        catalog_js = await client.get("/webapp/catalog-main.js")
    assert home.status_code == 200, home.text
    assert "hubIceTeaser" in home.text
    assert "ice-teaser-model.js" in home.text
    assert 'id="myTrainerBlock"' in home.text
    assert 'id="hubPrimaryPanel"' in home.text
    assert 'id="upcomingSection"' in home.text
    assert teaser_js.status_code == 200
    assert chips_js.status_code == 200
    assert "formatIceTeaser" in home_js.text
    assert "TrainerArenaChips" in catalog_js.text
    assert "trainer-arena-chips-model.js" in catalog.text
    assert "Работает на аренах" in catalog_js.text or "Работает на аренах" in chips_js.text


async def _bootstrap(telegram_id: int):
    with patch_client_init_auth(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(
                "/api/webapp/client/hub/bootstrap",
                headers={"X-Telegram-Init-Data": "mock"},
            )


@pytest.mark.asyncio
async def test_hub_bootstrap_ice_teaser_when_city_has_future_mk(
    app_use_test_db, db_session
) -> None:
    """AC-001: bootstrap carries the soonest public_skate/open_ice slot, no extra round-trip."""
    city_id = await _insert_city(db_session, name="Минск-055")
    later = await _insert_arena(db_session, city_id, name="Минск-Арена")
    soon = await _insert_arena(db_session, city_id, name="Чижовка")
    await _add_future_session(db_session, later, days_ahead=5, starts_at_local="18:00")
    await _add_future_session(
        db_session, soon, days_ahead=1, starts_at_local="11:00", price_adult_minor=1200
    )
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)
    await get_or_create_client(db_session, ctg, phone=phone, first_name="Клиент")
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state, city_id)
            VALUES (:t, 'idle', :cid)
            ON CONFLICT (telegram_id) DO UPDATE SET city_id = EXCLUDED.city_id
            """
        ),
        {"t": ctg, "cid": city_id},
    )
    await db_session.flush()

    direct = await get_hub_ice_teaser(db_session, city_id=city_id)
    assert direct is not None, "teaser SQL must see the future MK slot on db_session"

    resp = await _bootstrap(ctg)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert "ice_teaser" in payload
    teaser = payload["ice_teaser"]
    assert isinstance(teaser, dict)
    assert teaser["arena_name"] == "Чижовка"
    assert teaser["kind"] == "public_skate"
    assert teaser["starts_at_local"][:5] == "11:00"
    assert int(teaser["price_adult_minor"]) == 1200
    assert teaser.get("arena_id") == soon
    assert payload["bookings"] is not None
    assert payload["client_session"] is not None
    assert "passes" in payload


@pytest.mark.asyncio
async def test_hub_bootstrap_ice_teaser_hidden_without_future_mk(
    app_use_test_db, db_session
) -> None:
    """AC-002: no tier-A / no future MK → ice_teaser is null, not a «скоро» stub."""
    city_id = await _insert_city(db_session, name="Город-без-МК")
    await _insert_arena(db_session, city_id, name="Каток без слотов")
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)
    await get_or_create_client(db_session, ctg, phone=phone, first_name="Клиент")
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state, city_id)
            VALUES (:t, 'idle', :cid)
            ON CONFLICT (telegram_id) DO UPDATE SET city_id = EXCLUDED.city_id
            """
        ),
        {"t": ctg, "cid": city_id},
    )
    await db_session.flush()

    resp = await _bootstrap(ctg)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert "ice_teaser" in payload
    assert payload["ice_teaser"] is None


@pytest.mark.asyncio
async def test_hub_bootstrap_ice_teaser_hidden_without_session_city(
    app_use_test_db, db_session
) -> None:
    """No geolocation: without city_id on the session the teaser stays hidden."""
    city_id = await _insert_city(db_session, name="Минск-без-сессии")
    arena_id = await _insert_arena(db_session, city_id, name="Чижовка")
    await _add_future_session(db_session, arena_id, days_ahead=1)
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)
    await get_or_create_client(db_session, ctg, phone=phone, first_name="Клиент")
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state)
            VALUES (:t, 'idle')
            ON CONFLICT (telegram_id) DO NOTHING
            """
        ),
        {"t": ctg},
    )
    await db_session.flush()

    resp = await _bootstrap(ctg)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert "ice_teaser" in payload
    assert payload["ice_teaser"] is None
