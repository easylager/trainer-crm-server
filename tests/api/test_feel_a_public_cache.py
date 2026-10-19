"""FEEL-A: bfcache-friendly Cache-Control и учёт просмотров через beacon."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.catalog_consumer_events import KIND_PUBLIC_PAGE_VIEW
from src.application.ice_city_day import city_slug
from tests.api.public_page_view_beacon import post_catalog_page_view
from tests.api.test_public_place_page import _place


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_PUBLIC_CACHE = "private, max-age=30, stale-while-revalidate=300"


@pytest.mark.asyncio
async def test_catalog_home_cache_control(app_use_test_db, db_session) -> None:
    await db_session.commit()
    async with _client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == _PUBLIC_CACHE
    assert "Cookie" in resp.headers["vary"]


@pytest.mark.asyncio
async def test_city_selection_cache_control(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    slug = city_slug(place["city_name"])
    await db_session.commit()
    async with _client() as client:
        resp = await client.get(f"/c/{slug}")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == _PUBLIC_CACHE


@pytest.mark.asyncio
async def test_place_page_cache_control(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    await db_session.commit()
    async with _client() as client:
        resp = await client.get(place["path"])
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == _PUBLIC_CACHE


@pytest.mark.asyncio
async def test_html_get_does_not_record_public_page_view(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "test-catalog-actor-secret-0123456789abcdef")
    place = await _place(db_session)
    await db_session.commit()
    ua = f"Mozilla/5.0 FeelAHtml {uuid.uuid4().hex[:8]}"

    async with _client() as client:
        resp = await client.get(place["path"], headers={"User-Agent": ua})
        assert resp.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT 1 FROM catalog_consumer_events WHERE kind = :k AND payload->>'path' = :path LIMIT 1"
            ),
            {"k": KIND_PUBLIC_PAGE_VIEW, "path": place["path"]},
        )
    ).first()
    assert row is None


@pytest.mark.asyncio
async def test_prefetch_get_does_not_record_public_page_view(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "test-catalog-actor-secret-0123456789abcdef")
    place = await _place(db_session)
    await db_session.commit()
    ua = f"Mozilla/5.0 FeelAPrefetch {uuid.uuid4().hex[:8]}"

    async with _client() as client:
        prefetch = await client.get(
            place["path"],
            headers={"User-Agent": ua, "Sec-Purpose": "prefetch"},
        )
        assert prefetch.status_code == 200

    # Только своё место: общая тестовая БД хранит просмотры других тестов.
    row = (
        await db_session.execute(
            text(
                "SELECT 1 FROM catalog_consumer_events WHERE kind = :k AND payload->>'path' = :path LIMIT 1"
            ),
            {"k": KIND_PUBLIC_PAGE_VIEW, "path": place["path"]},
        )
    ).first()
    assert row is None


@pytest.mark.asyncio
async def test_page_view_beacon_records_public_page_view(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "test-catalog-actor-secret-0123456789abcdef")
    place = await _place(db_session)
    await db_session.commit()
    ua = f"Mozilla/5.0 FeelABeacon {uuid.uuid4().hex[:8]}"

    async with _client() as client:
        resp = await post_catalog_page_view(
            client,
            surface="place_page",
            path=place["path"],
            city_id=place["city_id"],
            arena_id=place["arena_id"],
            headers={"User-Agent": ua},
        )
    assert resp.status_code == 204

    row = (
        await db_session.execute(
            text(
                "SELECT surface, kind FROM catalog_consumer_events "
                "WHERE kind = :k AND payload->>'path' = :path ORDER BY id DESC LIMIT 1"
            ),
            {"k": KIND_PUBLIC_PAGE_VIEW, "path": place["path"]},
        )
    ).first()
    assert row is not None
    assert row[0] == "place_page"
    assert row[1] == KIND_PUBLIC_PAGE_VIEW


@pytest.mark.asyncio
async def test_page_view_beacon_ignores_mismatched_arena(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "test-catalog-actor-secret-0123456789abcdef")
    place = await _place(db_session)
    other_city = await _place(db_session)
    await db_session.commit()
    ua = f"Mozilla/5.0 FeelABeaconMismatch {uuid.uuid4().hex[:8]}"

    async with _client() as client:
        resp = await post_catalog_page_view(
            client,
            surface="place_page",
            path=place["path"],
            city_id=other_city["city_id"],
            arena_id=place["arena_id"],
            headers={"User-Agent": ua},
        )
    assert resp.status_code == 204

    row = (
        await db_session.execute(
            text("SELECT 1 FROM catalog_consumer_events WHERE kind = :k AND payload->>'path' = :path LIMIT 1"),
            {"k": KIND_PUBLIC_PAGE_VIEW, "path": place["path"]},
        )
    ).first()
    assert row is None
