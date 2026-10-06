"""TASK-191-A: главная каталога на /, лендинг тренера на /trainers."""

from __future__ import annotations

import json
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.catalog_consumer_events import KIND_PUBLIC_PAGE_VIEW
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from tests.api.test_public_ice_city_day import _add_today_session
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_public_place_page import _meta


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _json_ld(html: str) -> dict:
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert raw, "json-ld"
    return json.loads(raw.group(1))


@pytest.mark.asyncio
async def test_root_is_catalog_home_without_js(app_use_test_db, db_session) -> None:
    name = f"Главск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        home = await client.get("/")
        trainers = await client.get("/trainers")

    assert home.status_code == 200
    assert home.headers["content-type"].startswith("text/html")
    assert "<script" not in home.text.lower() or 'type="application/ld+json"' in home.text
    assert name in home.text
    assert f'/c/{slug}' in home.text
    assert f'/ice/{slug}/today' in home.text
    assert "Для тренеров" in home.text
    assert _meta(home.text, "robots") == "index, follow"

    assert trainers.status_code == 200
    assert 'id="landing-config"' in trainers.text
    assert "CRM для тренера" in trainers.text


@pytest.mark.asyncio
async def test_catalog_home_hides_empty_and_inactive_cities(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY,RU")
    visible = f"Видим {uuid.uuid4().hex[:6]}"
    empty = f"Пустой {uuid.uuid4().hex[:6]}"
    hidden = f"Москва {uuid.uuid4().hex[:6]}"
    vis_id = await _insert_city(db_session, name=visible, country="BY")
    await _insert_city(db_session, name=empty, country="BY")
    hidden_id = await _insert_city(db_session, name=hidden, country="RU")
    await db_session.execute(text("UPDATE cities SET is_active = false WHERE id = :id"), {"id": hidden_id})
    await _insert_arena(db_session, vis_id, name="Арена")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/")
    assert home.status_code == 200
    assert visible in home.text
    assert empty not in home.text
    assert hidden not in home.text


@pytest.mark.asyncio
async def test_catalog_home_jsonld_and_xss_safe_city_name(app_use_test_db, db_session) -> None:
    evil = '</script><img src=x onerror=alert(1)>'
    name = f"Злой {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=evil)
    await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/")
    assert home.status_code == 200
    assert home.text.count("</script>") == 1
    assert "<img" not in home.text
    ld = _json_ld(home.text)
    assert "@graph" in ld
    items = next(n for n in ld["@graph"] if n.get("@type") == "ItemList")["itemListElement"]
    names = [it.get("name") for it in items]
    assert evil in names


@pytest.mark.asyncio
async def test_catalog_home_records_public_page_view(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "test-catalog-actor-secret-0123456789abcdef")
    name = f"Метрик {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/", headers={"User-Agent": "Mozilla/5.0 Task191CatalogHome"})
    assert resp.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT surface, kind FROM catalog_consumer_events "
                "WHERE payload->>'path' = '/' ORDER BY id DESC LIMIT 1"
            )
        )
    ).first()
    assert row is not None
    assert row[0] == "catalog_home"
    assert row[1] == KIND_PUBLIC_PAGE_VIEW


@pytest.mark.asyncio
async def test_catalog_home_lists_upcoming_sessions_with_place_links(app_use_test_db, db_session) -> None:
    name = f"Сеансск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Ледовый")
    await _add_today_session(db_session, arena_id)
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    arena_slug = (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
    ).scalar_one()

    async with _client() as client:
        home = await client.get("/")
    assert home.status_code == 200
    assert f'/p/{slug}/{arena_slug}' in home.text
    assert "Лёд сегодня" in home.text
