"""TASK-232 / TASK-233: страница открытки /zovi/{code}, её картинки и календарь (trainer_crm_test)."""

from __future__ import annotations

import io
import json
import re

import pytest
from PIL import Image
from sqlalchemy import text

from src.application.png_render_cache import png_cache_stats, reset_png_cache_for_tests
from src.application.zovi_card_image import render_zovi_og, render_zovi_ticket
from src.application.zovi_card_page import decline, og_description, question_text, verdict
from src.shared.config import Settings


def _origin() -> str:
    """Тот же адрес, что строит страница: webapp_base_url, без него — адрес тестового клиента."""
    return (Settings().webapp_base_url or "").strip().rstrip("/") or "http://test"
from tests.api.test_ice_invites import (  # noqa: F401 — autouse-фикстура секрета и лимитов
    _actor_secret_and_limits,
    _at,
    _client,
    _create,
    _headers,
    _insert_session,
    _place,
)

_LONGEST_MINSK = "Ледовый дворец спорта Минской области"


async def _invite(db_session, *, kind: str = "public_skate", **overrides) -> tuple[str, int, dict]:
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=3), kind=kind)
    async with _client() as client:
        created = await _create(client, session_id, **overrides)
    assert created.status_code == 201, created.text
    return created.json()["code"], session_id, place


def _png_size(body: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(body)) as img:
        return img.size


def _embedded(html: str) -> dict:
    found = re.search(r'<script type="application/json" id="zoviData">(.*?)</script>', html, re.S)
    assert found is not None
    return json.loads(found.group(1))


@pytest.mark.asyncio
async def test_page_has_question_meta_and_noindex(app_use_test_db, db_session) -> None:
    code, _, place = await _invite(db_session, to_name="Лера")
    async with _client() as client:
        res = await client.get(f"/zovi/{code}", headers=_headers())
    assert res.status_code == 200
    html = res.text
    assert '<meta property="og:title" content="Лера, пойдёшь со мной на каток?"' in html
    assert '<meta name="robots" content="noindex, nofollow"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    origin = re.escape(_origin())
    assert re.search(rf'og:image" content="{origin}/zovi/{code}/og\.png\?v=[0-9a-f]{{10}}"', html)
    assert f'og:url" content="{_origin()}/zovi/{code}"' in html
    assert place["arena"] in html
    data = _embedded(html)
    assert data["code"] == code and data["state"] == "ok" and "my_answer" not in data
    assert "/static/shared/zovi-card.js?v=" in html


@pytest.mark.asyncio
async def test_hockey_session_asks_about_hockey_and_group_card_has_no_name(app_use_test_db, db_session) -> None:
    hockey, _, _ = await _invite(db_session, kind="hockey_practice", to_name="Аня")
    # Старые открытки без имени (до 2026-10-12) всё ещё открываются как «для компании».
    group, _, _ = await _invite(db_session, to_name="Лера")
    await db_session.execute(text("UPDATE ice_invites SET to_name = NULL WHERE code = :code"), {"code": group})
    await db_session.commit()
    async with _client() as client:
        first = await client.get(f"/zovi/{hockey}", headers=_headers())
        second = await client.get(f"/zovi/{group}", headers=_headers())
    assert 'og:title" content="Аня, пойдёшь со мной на хоккей?"' in first.text
    assert 'og:title" content="Пойдёшь со мной на каток?"' in second.text


@pytest.mark.asyncio
async def test_ssr_does_not_mark_opened_but_api_read_does(app_use_test_db, db_session) -> None:
    code, _, _ = await _invite(db_session)
    async with _client() as client:
        assert (await client.get(f"/zovi/{code}", headers=_headers())).status_code == 200
        assert (await client.get(f"/zovi/{code}/og.png", headers=_headers())).status_code == 200
    opened = (
        await db_session.execute(text("SELECT first_opened_at FROM ice_invites WHERE code = :c"), {"c": code})
    ).scalar_one()
    assert opened is None
    async with _client() as client:
        assert (await client.get(f"/api/public/invites/{code}", headers=_headers())).status_code == 200
    opened = (
        await db_session.execute(text("SELECT first_opened_at FROM ice_invites WHERE code = :c"), {"c": code})
    ).scalar_one()
    assert opened is not None


@pytest.mark.asyncio
async def test_unknown_code_is_404_page_with_catalog_link(app_use_test_db, db_session) -> None:
    async with _client() as client:
        res = await client.get("/zovi/zzzzzzzz", headers=_headers())
        bad = await client.get("/zovi/not-a-code", headers=_headers())
        png = await client.get("/zovi/zzzzzzzz/og.png", headers=_headers())
    assert res.status_code == 404 and bad.status_code == 404 and png.status_code == 404
    assert f'href="{_origin()}/"' in res.text
    assert "noindex" in res.text


@pytest.mark.asyncio
async def test_og_and_ticket_png_sizes(app_use_test_db, db_session) -> None:
    code, _, _ = await _invite(db_session, to_name="Лера")
    async with _client() as client:
        og = await client.get(f"/zovi/{code}/og.png", headers=_headers())
        ticket = await client.get(f"/zovi/{code}/ticket.png?t=3&s=14&f=1&k=0", headers=_headers())
    assert og.status_code == 200 and og.headers["content-type"] == "image/png"
    assert ticket.status_code == 200 and ticket.headers["content-type"] == "image/png"
    assert _png_size(og.content) == (1200, 630)
    assert _png_size(ticket.content) == (1080, 1350)


@pytest.mark.asyncio
async def test_ticket_clamps_forged_numbers_and_caches(app_use_test_db, db_session) -> None:
    code, _, _ = await _invite(db_session)
    reset_png_cache_for_tests()
    async with _client() as client:
        forged = await client.get(f"/zovi/{code}/ticket.png?t=999&s=-5&f=abc&k=1", headers=_headers())
        clamped = await client.get(f"/zovi/{code}/ticket.png?t=10&s=0&f=0&k=1", headers=_headers())
    assert forged.status_code == 200
    assert _png_size(forged.content) == (1080, 1350)
    # Зажатые значения — тот же ключ кэша: второй запрос не рендерит заново.
    assert forged.content == clamped.content
    assert png_cache_stats()["renders"] == 1


@pytest.mark.asyncio
async def test_event_ics_has_event_at_session_time(app_use_test_db, db_session) -> None:
    code, _, place = await _invite(db_session, kind="hockey_practice")
    starts = (
        await db_session.execute(text("SELECT starts_at_utc FROM ice_invites WHERE code = :c"), {"c": code})
    ).scalar_one()
    async with _client() as client:
        res = await client.get(f"/zovi/{code}/event.ics", headers=_headers())
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/calendar")
    body = res.text.replace("\r\n ", "")
    assert "BEGIN:VEVENT" in body
    assert f"DTSTART:{starts.strftime('%Y%m%dT%H%M%SZ')}" in body
    assert "SUMMARY:Хоккей с Максом" in body
    assert "ул. Ледовая\\, 1" in body


@pytest.mark.asyncio
async def test_page_for_removed_session_is_gone_with_data_for_js(app_use_test_db, db_session) -> None:
    code, session_id, _ = await _invite(db_session)
    await db_session.execute(text("DELETE FROM ice_sessions WHERE id = :id"), {"id": session_id})
    async with _client() as client:
        res = await client.get(f"/zovi/{code}", headers=_headers())
        og = await client.get(f"/zovi/{code}/og.png", headers=_headers())
    assert res.status_code == 200
    assert _embedded(res.text)["state"] == "gone"
    assert og.status_code == 200


def test_texts_match_the_card_model() -> None:
    assert question_text("Лера", "public_skate") == "Лера, пойдёшь со мной на каток?"
    assert question_text(None, "hockey_practice") == "Пойдёшь со мной на хоккей?"
    assert (decline("Макс", "gen"), decline("Макс", "dat"), decline("Макс", "ins")) == ("Макса", "Максу", "Максом")
    assert (decline("Лера", "gen"), decline("Лера", "dat"), decline("Лера", "ins")) == ("Леры", "Лере", "Лерой")
    assert (decline("Андрей", "gen"), decline("Андрей", "dat"), decline("Андрей", "ins")) == (
        "Андрея",
        "Андрею",
        "Андреем",
    )
    assert verdict(0, 0, False).startswith("Ответ «да» — с первой секунды")
    assert verdict(5, 1, False) == "Кнопка «Нет» сдалась первой."
    assert verdict(1, 0, True) == "Нажали «Нет». Это была «Да» в маскировке. Засчитано."


def _sample(name: str, to_name: str | None = "Анна-Мария") -> dict:
    return {
        "code": "abcd2345",
        "to_name": to_name,
        "from_name": "Alex",
        "kind": "public_skate",
        "state": "ok",
        "session": {
            "local_date": "2026-10-17",
            "starts_at_local": "19:15",
            "ends_at_local": "20:15",
            "starts_at_utc": "2026-10-17T16:15:00+00:00",
            "ends_at_utc": "2026-10-17T17:15:00+00:00",
            "arena": {"name": name, "address": "ул. Притыцкого, 27", "city": "Минск", "public_path": None},
        },
    }


def test_longest_minsk_arena_renders_on_both_images() -> None:
    invite = _sample(_LONGEST_MINSK)
    assert og_description(invite) == f"Сб, 17 окт · 19:15 · {_LONGEST_MINSK}"
    assert _png_size(render_zovi_og(invite)) == (1200, 630)
    assert _png_size(render_zovi_og(_sample(_LONGEST_MINSK, to_name=None))) == (1200, 630)
    ticket = render_zovi_ticket(invite, tries=5, seconds=600, falls=1, tricked=False)
    assert _png_size(ticket) == (1080, 1350)
    with Image.open(io.BytesIO(ticket)) as img:
        assert img.convert("L").getextrema()[0] < 60  # на билете есть тёмный текст, картинка не пустая
