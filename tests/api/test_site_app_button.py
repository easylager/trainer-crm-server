"""Кнопка «Приложение» на публичных страницах и вход для тренера на странице катка."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.style_b import app_button_href
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_app_button_marks_only_our_redirect() -> None:
    ours = "https://glideclub.by/api/public/catalog/open-telegram?startapp=catalog&surface=catalog_home"
    assert app_button_href(ours) == ours + "&via=app_button"
    assert app_button_href("https://t.me/glide_bot") == "https://t.me/glide_bot"


@pytest.mark.asyncio
async def test_home_has_floating_app_button_and_trainer_landing_does_not(app_use_test_db, db_session) -> None:
    async with _client() as client:
        home = (await client.get("/")).text
        landing = (await client.get("/trainers")).text
        script = await client.get("/static/share/app-button.js")
    host = re.search(r'<div class="b-appbtn-host tg-out" id="appButton">(.*?)</div>', home, re.S)
    assert host, "нет кнопки «Приложение» на главной"
    assert "via=app_button" in host.group(1) and ">Приложение<" in host.group(1)
    assert "Запись и напоминания в Telegram" in host.group(1)
    assert "/static/share/app-button.js?v=" in home
    assert script.status_code == 200
    assert 'id="appButton"' not in landing


@pytest.mark.asyncio
async def test_place_without_sessions_gets_floating_button_not_a_dock(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    async with _client() as client:
        html = (await client.get(place["path"])).text
    assert 'id="appButton"' in html
    assert 'id="placeShareDock"' not in html
    assert "b-tgdock" not in html


@pytest.mark.asyncio
async def test_coach_entry_closes_trainer_list_and_opens_mini_landing(app_use_test_db, db_session) -> None:
    place = await _place(db_session, name="ТЦ Замок")
    name = f"Анна{uuid.uuid4().hex[:4]}"
    async with _client() as client:
        await _trainer_on(db_session, client, place, first_name=name)
        html = (await client.get(place["path"])).text
        sheet_js = await client.get("/static/share/coach-sheet.js")
    section = re.search(r'<section class="b-sec b-sec--place" id="trainers">(.*?)</section>', html, re.S)
    assert section
    body = section.group(1)
    # Строка — после списка тренеров, а не над ним.
    assert body.index(name) < body.index("Тренируете на этом катке?")
    assert "Ученики «ТЦ Замок» записываются к вам сами" in body
    assert 'href="/join" data-coach-join' in body and 'class="b-coach-sheet__more" href="/trainers"' in body
    assert f"arena_id={place['arena_id']}" in body
    assert sheet_js.status_code == 200


@pytest.mark.asyncio
async def test_coach_beacons_are_recorded_separately(app_use_test_db, db_session, monkeypatch) -> None:
    from starlette.requests import Request

    from src.api.routes.catalog_consumer_telemetry import public_contact_click_beacon

    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "x" * 32)
    city_id = await _insert_city(db_session, name=f"Тренерск {uuid.uuid4().hex[:6]}")
    aid = await _insert_arena(db_session, city_id, name="Каток для тренера")
    await db_session.commit()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/public/catalog/contact-click",
        "headers": [(b"user-agent", b"Mozilla/5.0")],
        "query_string": b"",
    }
    for action in ("coach_open", "coach_join"):
        resp = await public_contact_click_beacon(
            Request(scope), action=action, surface="place_page", city_id=city_id, arena_id=aid,
            partner=None, session=db_session,
        )
        assert resp.status_code == 204
    actions = (
        await db_session.execute(
            text("SELECT payload->>'action' FROM catalog_consumer_events WHERE arena_id = :a ORDER BY id"),
            {"a": aid},
        )
    ).scalars().all()
    assert actions == ["coach_open", "coach_join"]


@pytest.mark.asyncio
async def test_open_telegram_records_app_button_clicks(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "x" * 32)
    place = await _place(db_session)
    async with _client() as client:
        resp = await client.get(
            "/api/public/catalog/open-telegram",
            params={
                "startapp": f"arena_{place['arena_id']}",
                "surface": "place_page",
                "via": "app_button",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    via = (
        await db_session.execute(
            text(
                "SELECT payload->>'via' FROM catalog_consumer_events "
                "WHERE arena_id = :a AND kind = 'public_telegram_cta' ORDER BY id DESC LIMIT 1"
            ),
            {"a": place["arena_id"]},
        )
    ).scalar_one()
    assert via == "app_button"
