"""TASK-425: хаб /c/minsk — лента «Лёд» по каткам и свёрнутые «Частые вопросы»; другие города не меняются."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.application.city_hub_seo import SEO_RICH_HUB_CITIES, build_seo_model, faq_card_html
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city

FAQ_SUMMARY = "Частые вопросы · "


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Minsk")).date()


async def _session(db, arena_id, *, day, hhmm, kind="public_skate", minutes=60, adult=None, child=None, rental=None):
    await create_ice_session(
        db,
        arena_id,
        local_date=day,
        starts_at_local=hhmm,
        duration_minutes=minutes,
        kind=kind,
        price_adult_minor=adult,
        price_child_minor=child,
        price_rental_minor=rental,
    )
    await db.flush()


async def _minsk(db) -> int:
    return await _insert_city(db, name="Минск")


def _tomorrow() -> date:
    return _today() + timedelta(days=1)


async def _get(path: str) -> str:
    invalidate_public_city_cache()
    async with _client() as client:
        return (await client.get(path)).text


def test_only_minsk_is_listed() -> None:
    assert SEO_RICH_HUB_CITIES == {"minsk"}


def _ribbon(html: str) -> str:
    return html.split('<div class="b-scroll">')[1].split("</section>")[0]


@pytest.mark.asyncio
async def test_minsk_ribbon_is_one_tile_per_rink_and_faq_is_folded(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    cheap = await _insert_arena(db_session, cid, name="Дешёвый каток")
    dear = await _insert_arena(db_session, cid, name="Дорогой каток")
    solo = await _insert_arena(db_session, cid, name="Одиночный каток")
    day = _tomorrow()
    for hh in ("10:00", "12:00", "08:30"):
        await _session(db_session, cheap, day=day, hhmm=hh, minutes=45, adult=700, child=500, rental=300)
    await _session(db_session, dear, day=day, hhmm="18:00", minutes=90, adult=1500, child=900)
    await _session(db_session, dear, day=day, hhmm="20:00", minutes=90, adult=1500, child=900)
    await _session(db_session, solo, day=day, hhmm="22:00", minutes=45)
    await db_session.commit()

    html = await _get("/c/minsk")
    ribbon = _ribbon(html)
    assert ribbon.count('class="b-tile"') == 3  # три катка, а не восемь сеансов
    assert ribbon.index("Дешёвый каток") < ribbon.index("Дорогой каток") < ribbon.index("Одиночный каток")
    assert "ещё 2 сеанса" in ribbon and "ещё 1 сеанс<" in ribbon
    assert ribbon.count("b-tile__more") == 2  # у одиночного сеанса строки нет
    assert "8:30" in ribbon  # бейдж — ближайший сеанс катка
    # FAQ: одна свёрнутая карточка, три вопроса, без FAQPage и без «сегодня/завтра»
    assert f"{FAQ_SUMMARY}3" in html and html.count("<details") >= 1
    faq = html.split(FAQ_SUMMARY)[1].split("</details>")[0]
    assert "Чаще всего — 45 минут" in faq and "от 45 до 90" in faq
    assert "от 7 BYN до 15 BYN" in faq.replace("\u00a0", " ")
    assert "Дешёвый каток" in faq.split("напрокат")[1]
    assert "сегодня" not in faq.lower() and "завтра" not in faq.lower()
    assert "FAQPage" not in html
    assert html.index(FAQ_SUMMARY) < html.index("Все места города")


@pytest.mark.asyncio
async def test_minsk_faq_skips_questions_without_data(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    a = await _insert_arena(db_session, cid, name="Каток 1")
    b = await _insert_arena(db_session, cid, name="Каток 2")
    await _session(db_session, a, day=_tomorrow(), hhmm="10:00", adult=900)
    await _session(db_session, b, day=_tomorrow(), hhmm="11:00", adult=900)
    await db_session.commit()
    html = await _get("/c/minsk")
    assert f"{FAQ_SUMMARY}2" in html  # прокат не указан - вопроса о прокате нет
    assert "взять коньки напрокат" not in html


@pytest.mark.asyncio
async def test_minsk_without_sessions_has_no_faq(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    await _insert_arena(db_session, cid, name="Каток 1")
    await _insert_arena(db_session, cid, name="Каток 2")
    await db_session.commit()
    html = await _get("/c/minsk")
    assert FAQ_SUMMARY not in html


@pytest.mark.asyncio
async def test_other_city_page_is_unchanged(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name="Молодечно")
    a = await _insert_arena(db_session, cid, name="Арена один")
    b = await _insert_arena(db_session, cid, name="Арена два")
    for arena in (a, b):
        await _session(db_session, arena, day=_tomorrow(), hhmm="10:00", adult=900, rental=300)
    await db_session.commit()
    html = await _get(f"/c/{city_slug('Молодечно')}")
    assert "b-seo" not in html and "b-tile__more" not in html
    assert FAQ_SUMMARY not in html


def _row(arena_id, day, hh, **kw):
    h, m = hh.split(":")
    start = time(int(h), int(m))
    return {
        "arena_id": arena_id,
        "kind": kw.get("kind", "public_skate"),
        "local_date": day,
        "starts_at_local": start,
        "ends_at_local": time((int(h) + 1) % 24, int(m)),
        "price_adult_minor": kw.get("adult"),
        "price_child_minor": kw.get("child"),
        "price_rental_minor": kw.get("rental"),
        "currency_code": "BYN",
    }


def _view(places, model):
    return {
        "city": {"name": "Минск"},
        "slug": "minsk",
        "places": places,
        "seo_text": model,
        "skate_counts": {"weekend": 0},
        "skate_window_arena_counts": {},
    }


def test_no_prices_no_rental_means_only_duration_question() -> None:
    day = date(2026, 11, 20)
    places = [{"id": 1, "name": "А", "slug": "a", "address": ""}, {"id": 2, "name": "Б", "slug": "b", "address": ""}]
    model = build_seo_model([_row(1, day, "10:00"), _row(2, day, "11:00")], places)
    html = faq_card_html(_view(places, model))
    assert "Частые вопросы · 1" in html and "Сколько длится сеанс" in html
    assert "Сколько стоит" not in html and "напрокат" not in html


def test_no_sessions_no_model_no_html() -> None:
    assert build_seo_model([], [{"id": 1, "name": "А", "slug": "a"}]) is None
    assert faq_card_html(_view([], None)) == ""


@pytest.mark.asyncio
async def test_minsk_hub_sql_budget_does_not_grow_with_rinks(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    ids = [await _insert_arena(db_session, cid, name=f"Каток {i}") for i in range(2)]
    for aid in ids:
        await _session(db_session, aid, day=_tomorrow(), hhmm="10:00", adult=900, rental=300)
    await db_session.commit()
    bind = db_session.sync_session.get_bind()
    counts = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        if (statement or "").lstrip().upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    try:
        await _get("/c/minsk")
        small = counts["n"]
        for i in range(10):
            aid = await _insert_arena(db_session, cid, name=f"Новый {i}")
            await _session(db_session, aid, day=_tomorrow(), hhmm="11:00", adult=900, rental=300)
        await db_session.commit()
        counts["n"] = 0
        await _get("/c/minsk")
        big = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", _before)
    assert abs(big - small) <= 1, (small, big)
