"""TASK-191-A: главная каталога на /, лендинг тренера на /trainers."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.application.catalog_consumer_events import KIND_PUBLIC_PAGE_VIEW
from src.application.catalog_home_page import parse_city_session_count_from_home
from src.application.ice_city_day import city_slug, get_city_ice_day, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_ice_city_day import _add_today_session, _minsk_now
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_public_place_page import _meta

_HOME_SQL_MAX = 6


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
    assert f'/ice/{slug}/today' not in home.text
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


def _count_sql(db_session):
    bind = db_session.sync_session.get_bind()
    counts = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        head = (statement or "").lstrip().upper()
        if head.startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    return bind, counts, _before


@pytest.mark.asyncio
async def test_catalog_home_session_counts_match_ice_today(app_use_test_db, db_session) -> None:
    city_specs: list[tuple[int, str]] = []
    for _ in range(3):
        name = f"Счёт {uuid.uuid4().hex[:6]}"
        city_id = await _insert_city(db_session, name=name)
        arena_id = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
        await _add_today_session(db_session, arena_id)
        city_specs.append((city_id, name))
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/")
    assert home.status_code == 200

    for city_id, name in city_specs:
        day = await get_city_ice_day(db_session, city_id=city_id)
        on_home = parse_city_session_count_from_home(home.text, name)
        assert on_home is not None
        expected = int(day["session_count"] or 0) if day.get("is_today") else 0
        assert on_home == expected, (name, day.get("is_today"), day.get("session_count"))


@pytest.mark.asyncio
async def test_catalog_home_sql_budget_is_flat_in_city_count(app_use_test_db, db_session) -> None:
    invalidate_public_city_cache()
    one_id = await _insert_city(db_session, name=f"Один {uuid.uuid4().hex[:6]}")
    await _insert_arena(db_session, one_id, name="Арена")
    await db_session.commit()
    invalidate_public_city_cache()

    bind, counts, before = _count_sql(db_session)
    try:
        async with _client() as client:
            resp_one = await client.get("/")
        one_sql = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", before)
    assert resp_one.status_code == 200

    for _ in range(4):
        cid = await _insert_city(db_session, name=f"Пять {uuid.uuid4().hex[:6]}")
        await _insert_arena(db_session, cid, name="Арена")
    await db_session.commit()
    invalidate_public_city_cache()

    bind, counts, before = _count_sql(db_session)
    try:
        async with _client() as client:
            resp_five = await client.get("/")
        five_sql = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", before)
    assert resp_five.status_code == 200
    assert one_sql == five_sql
    assert one_sql <= _HOME_SQL_MAX


@pytest.mark.asyncio
async def test_catalog_home_evening_block_shows_tomorrow_label(app_use_test_db, db_session, monkeypatch) -> None:
    evening_minsk = datetime(2026, 10, 10, 22, 0, tzinfo=ZoneInfo("Europe/Minsk"))
    fixed_now = evening_minsk.astimezone(timezone.utc)
    monkeypatch.setattr("src.application.catalog_home_page._utc_now", lambda: fixed_now)

    name = f"Вечер {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Ночной каток")
    tomorrow = (evening_minsk + timedelta(days=1)).date()
    await create_ice_session(
        db_session,
        arena_id,
        local_date=tomorrow,
        starts_at_local="10:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
    )
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/")
    assert home.status_code == 200
    assert "Ближайший лёд" in home.text
    assert "завтра" in home.text
    assert "10:00–11:00" in home.text
    assert "10:00:00" not in home.text
    assert '<h2 class="section">Лёд сегодня</h2>' not in home.text


@pytest.mark.asyncio
async def test_catalog_home_city_order_minsk_first_then_by_activity(app_use_test_db, db_session) -> None:
    minsk_id = await _insert_city(db_session, name="Минск", country="BY")
    quiet_name = f"Тихий {uuid.uuid4().hex[:4]}"
    busy_name = f"Живой {uuid.uuid4().hex[:4]}"
    quiet_id = await _insert_city(db_session, name=quiet_name, country="BY")
    busy_id = await _insert_city(db_session, name=busy_name, country="BY")
    await db_session.execute(text("UPDATE cities SET sort_order = 1 WHERE id = :id"), {"id": quiet_id})
    await db_session.execute(text("UPDATE cities SET sort_order = 99 WHERE id = :id"), {"id": minsk_id})
    await _insert_arena(db_session, minsk_id, name="Минск арена")
    await _insert_arena(db_session, quiet_id, name="Тихая")
    busy_arena = await _insert_arena(db_session, busy_id, name="Живая")
    await _add_today_session(db_session, busy_arena)
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/")
    assert home.status_code == 200
    names = re.findall(r'<h2 class="city__name"><a href="[^"]+">([^<]+)</a></h2>', home.text)
    assert names[0] == "Минск"
    assert names.index(busy_name) < names.index(quiet_name)


@pytest.mark.asyncio
async def test_catalog_home_ice_today_link_only_with_sessions_today(app_use_test_db, db_session) -> None:
    with_sessions = f"Сеансы {uuid.uuid4().hex[:6]}"
    without = f"Без льда {uuid.uuid4().hex[:6]}"
    cid1 = await _insert_city(db_session, name=with_sessions)
    cid2 = await _insert_city(db_session, name=without)
    a1 = await _insert_arena(db_session, cid1, name="Каток")
    await _insert_arena(db_session, cid2, name="Пустой")
    await _add_today_session(db_session, a1)
    await db_session.commit()
    invalidate_public_city_cache()
    slug_with = city_slug(with_sessions)
    slug_without = city_slug(without)

    async with _client() as client:
        home = await client.get("/")
    assert home.status_code == 200
    assert f'/ice/{slug_with}/today' in home.text
    assert f'/ice/{slug_without}/today' not in home.text


@pytest.mark.asyncio
async def test_catalog_home_country_groups_and_headline_when_ru_present(
    app_use_test_db, db_session, monkeypatch
) -> None:
    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY,RU")
    by_name = f"Брест {uuid.uuid4().hex[:4]}"
    ru_name = f"Питер {uuid.uuid4().hex[:4]}"
    by_id = await _insert_city(db_session, name=by_name, country="BY")
    ru_id = await _insert_city(db_session, name=ru_name, country="RU")
    await _insert_arena(db_session, by_id, name="BY арена")
    await _insert_arena(db_session, ru_id, name="RU арена")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/")
    assert home.status_code == 200
    assert "<h1>Катки — расписание по городам</h1>" in home.text
    assert "Катки Беларуси и России" in home.text
    assert "Катки Беларуси</h1>" not in home.text
    cities_block = home.text.split('<h2 class="section">Города</h2>', 1)[1].split('<h2 class="section">', 1)[0]
    assert '<h3 class="country-group__title">Беларусь</h3>' in cities_block
    assert cities_block.index(by_name) < cities_block.index('<h3 class="country-group__title">Россия</h3>')
    assert cities_block.index('<h3 class="country-group__title">Россия</h3>') < cities_block.index(ru_name)

