"""TASK-146: подборка /c/{город} — то, чем делятся из каталога (город + тип + окно)."""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug
from tests.api.test_catalog_shops import _admin_create_shop
from tests.api.test_ice_windows_and_nearest import _session
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_selection_page_shows_places_sessions_and_keeps_filters(app_use_test_db, db_session) -> None:
    name = f"Подборинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await _session(db_session, rink, day=date.today() + timedelta(days=2), hhmm="18:45")
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/c/{slug}")
        by_id = await client.get(f"/c/{city_id}")
        img = await client.get(f"/c/{slug}/og.png")
        missing = await client.get("/c/nowhere-at-all")
    assert page.status_code == 200
    assert "18:45" in page.text and "все места" in page.text.lower()
    assert f'href="/p/{slug}/' in page.text, "место в подборке ведёт на свою страницу"
    assert by_id.status_code == 301 and by_id.headers["location"] == f"/c/{slug}"
    assert Image.open(io.BytesIO(img.content)).size == (1200, 630)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_unfiltered_selection_matches_feed_without_shops(app_use_test_db, db_session) -> None:
    """TASK-217: «все места» — как лента. Магазин только по чипу, смесь не называется катками."""
    name = f"Лентаград {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name="Ледовый")
    gym_id = await _insert_arena(db_session, city_id, name="Зал Силы")
    await db_session.execute(
        text("UPDATE arenas SET venue_type = 'gym' WHERE id = :id"),
        {"id": gym_id},
    )
    await db_session.commit()
    shop = f"CCMshop {uuid.uuid4().hex[:4]}"
    await _admin_create_shop(city_id, shop)
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/c/{slug}")
        share = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": city_id, "record": "false"},
        )
        shops = await client.get(f"/c/{slug}", params={"t": "shop"})
    assert page.status_code == 200
    assert "Ледовый" in page.text and "Зал Силы" in page.text
    assert shop not in page.text
    body = share.json()["share_body"]
    assert "Ледовый" in body and "Зал Силы" in body
    assert shop not in body
    assert "2 места" in body
    assert "каток" not in body.lower()
    assert shop in shops.text


@pytest.mark.asyncio
async def test_shop_selection_and_share_api(app_use_test_db, db_session) -> None:
    name = f"Магазинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await db_session.commit()
    await _admin_create_shop(city_id, f"Лезвие {uuid.uuid4().hex[:4]}")
    async with _client() as client:
        page = await client.get(f"/c/{city_slug(name)}", params={"t": "shop"})
        share = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": city_id, "venue_type": "shop", "channel": "copy"},
        )
        preview = await client.get(
            "/api/public/ice/selection/share", params={"city_id": city_id, "when": "auto", "record": "false"}
        )
    assert "магазины и заточка" in page.text
    body = share.json()
    assert body["share_url"].endswith(f"/c/{city_slug(name)}?t=shop")
    assert body["share_body"].startswith(f"{name} · магазины и заточка")
    assert body["og_image_url"].endswith("/og.png?t=shop")
    assert body["story_image_url"].endswith("/story.png?t=shop")
    assert preview.json()["when"] in ("today_evening", "tomorrow", "weekend")
    assert "/story.png" in preview.json()["story_image_url"]
    rows = (
        (
            await db_session.execute(
                text("SELECT payload FROM client_share_events WHERE kind = 'selection' AND city_id = :c"),
                {"c": city_id},
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0]["channel"] == "copy" and rows[0]["venue_type"] == "shop"


def _og(html: str, prop: str) -> str:
    import re

    match = re.search(rf'<meta property="{prop}" content="([^"]*)"', html)
    assert match, prop
    return match.group(1)


@pytest.mark.asyncio
async def test_selection_preview_and_telegram_keep_the_window(
    app_use_test_db, db_session, monkeypatch
) -> None:
    """Превью не говорит «сегодня», а «Открыть в Telegram» открывает то же окно."""
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_bot")
    monkeypatch.setenv("CLIENT_MINI_APP_SHORT_NAME", "")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "true")
    name = f"Окноград {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/c/{slug}", params={"w": "weekend"})
        share = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": city_id, "when": "weekend", "record": "false"},
        )
    assert page.status_code == 200
    og_title = _og(page.text, "og:title").lower()
    for stale in ("сегодня", "завтра", "выходн"):
        assert stale not in og_title
        assert stale not in share.json()["share_body"].lower()
    assert _og(page.text, "og:image").startswith("http")
    assert f"startapp=catalog_{city_id}_skate_weekend" in page.text
    assert "/api/public/catalog/open-telegram" in page.text
    assert "В выходные" in page.text, "живая страница говорит ту же подпись, что и меню Mini App"
