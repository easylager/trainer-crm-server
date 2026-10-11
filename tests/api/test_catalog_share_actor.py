"""Каталожный шаринг пишет стабильный actor_hash и не отказывает анониму."""

from __future__ import annotations

import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.catalog_consumer_events import (
    CATALOG_METRICS_EXCLUDED_TELEGRAM_IDS,
    public_actor_hash,
    telegram_actor_hash,
)
from src.shared.config import Settings
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.shared.test_telegram_webapp import _build_signed_init_data

_TOKEN = "123456:ABC-SHARE"
_SECRET = "test-catalog-actor-secret-0123456789abcdef"
_IP = "203.0.113.77"
_UA = "share-actor-test"


class _ClientSecrets:
    telegram_bot_token_client = _TOKEN
    vk_mini_app_protected_key = ""


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _anon_headers() -> dict[str, str]:
    return {"X-Forwarded-For": _IP, "User-Agent": _UA}


def _signed(user_id: int) -> dict[str, str]:
    raw = _build_signed_init_data(_TOKEN, user_id=user_id, auth_date=int(time.time()))
    return {**_anon_headers(), "X-Telegram-Init-Data": raw}


async def _place(db_session) -> dict:
    name = f"Шер{uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await db_session.flush()
    return {"city_id": city_id, "arena_id": arena_id}


async def _rows(db_session, city_id: int) -> list[tuple]:
    result = await db_session.execute(
        text(
            """
            SELECT kind, actor_hash
            FROM client_share_events
            WHERE city_id = :cid
            ORDER BY id
            """
        ),
        {"cid": city_id},
    )
    return [(str(kind), actor) for kind, actor in result.all()]


@pytest.fixture
def _share_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _SECRET)
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientSecrets())


@pytest.mark.asyncio
async def test_valid_init_data_stores_telegram_actor_on_all_three(
    app_use_test_db, db_session, _share_secrets
) -> None:
    place = await _place(db_session)
    user_id = 515151
    expected = telegram_actor_hash(user_id)
    headers = _signed(user_id)
    async with _client() as client:
        ice = await client.get(f"/api/public/ice/share/{place['city_id']}", headers=headers)
        selection = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": place["city_id"], "record": "true"},
            headers=headers,
        )
        arena = await client.get(
            f"/api/public/arenas/{place['arena_id']}/share",
            params={"record": "true"},
            headers=headers,
        )
    assert ice.status_code == 200, ice.text
    assert selection.status_code == 200, selection.text
    assert arena.status_code == 200, arena.text
    rows = await _rows(db_session, place["city_id"])
    assert {kind for kind, _actor in rows} == {"ice_city_day", "selection", "place"}
    assert {actor for _kind, actor in rows} == {expected}


@pytest.mark.asyncio
async def test_missing_and_garbage_credential_stay_200_with_public_actor(
    app_use_test_db, db_session, _share_secrets
) -> None:
    place = await _place(db_session)
    expected = public_actor_hash(client_ip=_IP, user_agent=_UA)
    assert expected
    async with _client() as client:
        missing = await client.get(
            f"/api/public/ice/share/{place['city_id']}",
            headers=_anon_headers(),
        )
        garbage = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": place["city_id"]},
            headers={**_anon_headers(), "X-Telegram-Init-Data": "not-a-credential"},
        )
    assert missing.status_code == 200, missing.text
    assert garbage.status_code == 200, garbage.text
    rows = await _rows(db_session, place["city_id"])
    assert len(rows) == 2
    assert {actor for _kind, actor in rows} == {expected}


@pytest.mark.asyncio
async def test_excluded_telegram_and_record_false_write_nothing(
    app_use_test_db, db_session, _share_secrets
) -> None:
    place = await _place(db_session)
    staff = next(iter(CATALOG_METRICS_EXCLUDED_TELEGRAM_IDS))
    async with _client() as client:
        preview = await client.get(
            f"/api/public/arenas/{place['arena_id']}/share",
            params={"record": "false"},
            headers=_signed(424242),
        )
        selection = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": place["city_id"], "record": "false"},
            headers=_signed(424242),
        )
        excluded = await client.get(
            f"/api/public/ice/share/{place['city_id']}",
            headers=_signed(staff),
        )
    assert preview.status_code == 200
    assert selection.status_code == 200
    assert excluded.status_code == 200
    assert await _rows(db_session, place["city_id"]) == []


@pytest.mark.asyncio
async def test_without_actor_secret_share_stores_null(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.delenv("CATALOG_ACTOR_HMAC_SECRET", raising=False)
    monkeypatch.setattr(
        "src.shared.config.get_settings",
        lambda: Settings(catalog_actor_hmac_secret=None),
    )
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientSecrets())
    place = await _place(db_session)
    async with _client() as client:
        resp = await client.get(
            f"/api/public/ice/share/{place['city_id']}",
            headers=_signed(424242),
        )
    assert resp.status_code == 200, resp.text
    rows = await _rows(db_session, place["city_id"])
    assert len(rows) == 1
    assert rows[0][1] is None
