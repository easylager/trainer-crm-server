"""TASK-181: публичные поверхности каталога — инъекции и мелкие дыры.

AC-1 /p/ и /c/ с именем-плейсхолдером и адресом-тегом — без исполняемого HTML.
AC-3 ``tickets_url=javascript:…`` не попадает в href.
AC-4 ``/r/tg/{id}`` тренера вне каталога — 404.
AC-5 ``/api/public/trainers?limit=100000`` — не больше 50 записей.
Плюс: вход названия/адреса площадки отсекает разметку.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug
from src.shared.catalog_visibility import CATALOG_STATE_HIDDEN
from src.shared.html_template import fill_placeholders, json_for_script, safe_external_url
from src.shared.validation import has_markup_chars
from tests.api.test_ice_windows_and_nearest import _session
from tests.api.test_lead_mode_public_integration import _set_telegram_username
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_public_catalog_integration import _create_active_trainer_via_api
from tests.api.test_public_place_page import _json_ld, _meta, _place
from tests.api.test_webapp_client_miniapp_integration import _require_seed_ids

# Repro из аудита: имя с поздним плейсхолдером + адрес-тег.
EVIL_NAME = "Rink> __JSONLD__"
EVIL_ADDRESS = "<img src=x onerror=alert(1)>"


def _client(**kw) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", **kw)


def _assert_no_live_markup(html: str) -> None:
    assert "<img src=x" not in html, "адрес попал в разметку живым тегом"
    # Ни одного сырого JSON-LD вне его <script>: плейсхолдер не развернулся в атрибуте.
    assert html.count('"@context"') == 1
    for m in re.finditer(r'<meta [^>]*content="([^"]*)"', html):
        assert "<" not in m.group(1) and '"@' not in m.group(1), m.group(0)


# --- чистые помощники ---


def test_fill_placeholders_is_single_pass() -> None:
    out = fill_placeholders("<t>__A__</t><s>__B__</s>", {"__A__": "x __B__", "__B__": '{"k":"<v>"}'})
    assert out == '<t>x __B__</t><s>{"k":"<v>"}</s>'
    assert fill_placeholders("__UNKNOWN__", {}) == "__UNKNOWN__"


def test_json_for_script_cannot_close_the_tag() -> None:
    raw = json_for_script({"name": "</script><!-- & <b>"})
    assert "<" not in raw and ">" not in raw and "&" not in raw
    assert json.loads(raw) == {"name": "</script><!-- & <b>"}


def test_safe_external_url_allows_only_http_s() -> None:
    assert safe_external_url("https://ticket.by/x") == "https://ticket.by/x"
    assert safe_external_url(" http://a.by ") == "http://a.by"
    for bad in ("javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,x", "//evil", "vbscript:x", None, ""):
        assert safe_external_url(bad) is None, bad


def test_contacts_block_drops_javascript_tickets_url() -> None:
    from src.application.place_page import _contacts_html

    html = _contacts_html({"tickets_url": "javascript:alert(1)", "website_url": "javascript:alert(2)"})
    assert "javascript:" not in html
    ok = _contacts_html({"tickets_url": "https://ticket.by/rink"})
    assert 'href="https://ticket.by/rink"' in ok


def test_markup_chars_detection_keeps_legit_names() -> None:
    for legit in ('Ледовый дворец "Юность"', "Арена «Минск»", "Bowl & Roll", "O'Neil rink", "ул. Ленина, 1/2"):
        assert not has_markup_chars(legit), legit
    for bad in (EVIL_ADDRESS, "Rink>", "a<b", "x\x00y"):
        assert has_markup_chars(bad), bad


@pytest.mark.asyncio
async def test_trainer_arena_create_rejects_markup() -> None:
    from src.application.trainer_arena_create_use_cases import create_trainer_arena

    # Проверка срабатывает до первого обращения к сессии.
    with pytest.raises(ValueError, match="< и >"):
        await create_trainer_arena(None, 1, name=EVIL_NAME, address="ул. Ледовая, 1")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="< и >"):
        await create_trainer_arena(None, 1, name="Каток", address=EVIL_ADDRESS)  # type: ignore[arg-type]


# --- AC-1: /p/ и /c/ ---


@pytest.mark.asyncio
async def test_place_page_with_repro_name_and_address_has_no_live_html(app_use_test_db, db_session) -> None:
    place = await _place(db_session, name=EVIL_NAME)
    await db_session.execute(
        text("UPDATE arenas SET address = :a WHERE id = :id"), {"a": EVIL_ADDRESS, "id": place["arena_id"]}
    )
    await db_session.commit()
    async with _client() as client:
        resp = await client.get(place["path"])
    assert resp.status_code == 200, resp.text
    html = resp.text
    _assert_no_live_markup(html)
    assert "&lt;img src=x onerror=alert(1)&gt;" in html, "адрес виден текстом"
    assert "__JSONLD__" in _meta(html, "og:title"), "плейсхолдер в имени остаётся текстом"
    ld_raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
    assert "<" not in ld_raw
    ld = _json_ld(html)
    assert ld["name"] == EVIL_NAME and ld["address"]["streetAddress"] == EVIL_ADDRESS


@pytest.mark.asyncio
async def test_selection_page_with_repro_name_and_address_has_no_live_html(app_use_test_db, db_session) -> None:
    city = f"Безопасинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=city)
    rink = await _insert_arena(db_session, city_id, name=EVIL_NAME, address=EVIL_ADDRESS)
    await _session(db_session, rink, day=date.today() + timedelta(days=1), hhmm="18:45")
    await db_session.commit()
    async with _client() as client:
        resp = await client.get(f"/c/{city_slug(city)}")
    assert resp.status_code == 200, resp.text
    html = resp.text
    assert "18:45" in html, "арена попала в подборку"
    _assert_no_live_markup(html)
    ld_raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
    assert "<" not in ld_raw and ">" not in ld_raw, "JSON-LD экранирует угловые скобки целиком"
    assert EVIL_NAME in [i["name"] for i in json.loads(ld_raw)["itemListElement"]]


# --- AC-4: /r/tg/{id} ---


@pytest.mark.asyncio
async def test_tg_redirect_only_for_catalog_listed_trainers(app_use_test_db, db_session) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with _client(follow_redirects=False) as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _set_telegram_username(db_session, tid, "listed_handle_181")
        listed = await client.get(f"/r/tg/{tid}")
        await db_session.execute(
            text("UPDATE trainers SET catalog_state = :s WHERE id = :id"), {"s": CATALOG_STATE_HIDDEN, "id": tid}
        )
        await db_session.commit()
        hidden = await client.get(f"/r/tg/{tid}")
    assert listed.status_code == 302 and listed.headers["location"].startswith("https://t.me/listed_handle_181")
    assert hidden.status_code == 404
    assert "listed_handle_181" not in hidden.text


def test_contact_url_for_unlisted_card_skips_the_redirect() -> None:
    from src.api.routes.public import _build_contact_telegram_url

    assert _build_contact_telegram_url(5, "@good_handle", listed=True) == "/r/tg/5"
    assert _build_contact_telegram_url(5, "@good_handle", listed=False) == "https://t.me/good_handle"
    assert _build_contact_telegram_url(5, "bad", listed=False) is None


def test_bot_write_link_avoids_404_for_unlisted_trainer() -> None:
    from src.bot.handlers.client_handlers import _client_trainer_write_url

    base = "https://app.example"
    trainer = {"id": 9, "telegram_id": 1, "telegram_username": "coach_nine"}
    assert _client_trainer_write_url(base=base, trainer={**trainer, "catalog_state": "published"}).startswith(
        base + "/r/tg/9?"
    )
    assert _client_trainer_write_url(base=base, trainer={**trainer, "catalog_state": "hidden"}) == (
        "https://t.me/coach_nine"
    )


# --- AC-5: limit clamp ---


@pytest.mark.asyncio
async def test_public_trainers_limit_is_clamped(app_use_test_db, monkeypatch) -> None:
    import src.api.routes.public as public_routes

    seen: dict[str, int] = {}

    async def _fake_list(session, *, limit, offset, **_kw):
        seen["limit"], seen["offset"] = limit, offset
        return [], 0

    async def _fake_groups(session, *, limit, offset, **_kw):
        seen["groups_limit"] = limit
        return [], 0

    monkeypatch.setattr(public_routes, "list_active_trainers_for_client", _fake_list)
    monkeypatch.setattr(public_routes, "list_open_training_groups_catalog", _fake_groups)
    async with _client() as client:
        r1 = await client.get("/api/public/trainers", params={"limit": 100000, "offset": -5})
        r2 = await client.get("/api/public/training-groups", params={"limit": 100000})
    assert r1.status_code == 200 and r2.status_code == 200
    assert seen["limit"] == 50 and seen["offset"] == 0
    assert seen["groups_limit"] == 50


@pytest.mark.asyncio
async def test_public_trainers_limit_real_query_returns_at_most_50(app_use_test_db) -> None:
    async with _client() as client:
        resp = await client.get("/api/public/trainers", params={"limit": 100000})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) <= 50
