"""Страница «Предложить место» /suggest (PDEC-028)."""

import html
import json
import re

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app


def _prefill(body: str):
    marker = 'data-prefill-city="'
    start = body.index(marker) + len(marker)
    return json.loads(html.unescape(body[start : body.index('"', start)]))


@pytest.mark.asyncio
async def test_suggest_page_renders_form_shell(app_use_test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/suggest")
    assert r.status_code == 200
    body = r.text
    assert "/static/shared/place-suggest-form.js?v=" in body
    assert "/static/shared/place-suggest-form.css?v=" in body
    assert not re.search(r"__[A-Z][A-Z0-9_]+__", body)
    assert _prefill(body) is None
    assert 'id="appButton"' not in body  # своя нижняя панель — без плавающей «Приложение»


@pytest.mark.asyncio
async def test_suggest_page_prefills_public_city_only(app_use_test_db, db_session):
    active = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, sort_order, is_active, country) "
                "VALUES ('Тестоград', 1, true, 'BY') RETURNING id"
            )
        )
    ).scalar_one()
    hidden = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, sort_order, is_active, country) "
                "VALUES ('Скрытоград', 1, false, 'BY') RETURNING id"
            )
        )
    ).scalar_one()
    await db_session.flush()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.get(f"/suggest?city={active}")
        off = await client.get(f"/suggest?city={hidden}")
    assert _prefill(ok.text) == {
        "city_id": active, "name": "Тестоград", "region": None, "country": "BY", "is_new": False,
    }
    assert _prefill(off.text) is None


@pytest.mark.asyncio
async def test_suggest_form_assets_are_served():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        css = await client.get("/static/shared/place-suggest-form.css")
        js = await client.get("/static/shared/place-suggest-form.js")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert "PlaceSuggestForm" in js.text


@pytest.mark.asyncio
async def test_city_hub_links_to_suggest_with_city(app_use_test_db, db_session):
    from src.application.ice_city_day import city_slug, invalidate_public_city_cache

    cid = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, sort_order, is_active, country) "
                "VALUES ('Предлагайск', 1, true, 'BY') RETURNING id"
            )
        )
    ).scalar_one()
    await db_session.flush()
    invalidate_public_city_cache()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/c/{city_slug('Предлагайск')}")
    assert r.status_code == 200
    assert f'href="/suggest?city={cid}"' in r.text
