"""TASK-146: маркетинговая ссылка /go — в Telegram (каталог или кнопка «Каталог»), с учётом источника."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.catalog_deep_links import build_catalog_deep_link_reply
from src.application.ice_city_day import city_slug
from tests.api.test_public_arenas import _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_go_opens_the_catalog_in_telegram_and_counts_the_source(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_bot")
    monkeypatch.setenv("CLIENT_MINI_APP_SHORT_NAME", "app")
    source = f"flyer-{uuid.uuid4().hex[:6]}"
    async with _client() as client:
        resp = await client.get(f"/go/{source}", headers={"referer": "https://instagram.com/p/1"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://t.me/glide_bot/app?startapp=catalog"
    row = (
        await db_session.execute(
            text("SELECT target, referer_host, city_id FROM catalog_entry_clicks WHERE source = :s"), {"s": source}
        )
    ).one()
    assert row == ("startapp", "instagram.com", None)


@pytest.mark.asyncio
async def test_go_with_city_and_without_short_name_lands_on_the_bot_button(
    app_use_test_db, db_session, monkeypatch
) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_bot")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)
    name = f"Гоусск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await db_session.commit()
    async with _client() as client:
        resp = await client.get(f"/go/Insta/{city_slug(name)}")
    assert resp.headers["location"] == f"https://t.me/glide_bot?start=catalog_{city_id}"
    # Бот отвечает одной кнопкой «Каталог» на каталог этого города.
    reply = await build_catalog_deep_link_reply(db_session, f"catalog_{city_id}", webapp_base_url="https://g.example")
    assert reply["url"] == f"https://g.example/webapp/ice?city_id={city_id}"
    bare = await build_catalog_deep_link_reply(db_session, "catalog", webapp_base_url="https://g.example")
    assert bare["button_text"] == "Открыть каталог" and bare["url"] == "https://g.example/webapp/ice"
    assert "Карта льда" in bare["text"]


@pytest.mark.asyncio
async def test_go_never_dead_ends(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.delenv("CLIENT_BOT_USERNAME", raising=False)
    async with _client() as client:
        web = await client.get("/go")
        junk = await client.get("/go/%3Cscript%3E")
    assert web.status_code == 302 and web.headers["location"].endswith("/webapp/ice")
    assert junk.status_code == 302
    last = (
        await db_session.execute(text("SELECT source, target FROM catalog_entry_clicks ORDER BY id DESC LIMIT 1"))
    ).one()
    assert last == ("other", "web")
