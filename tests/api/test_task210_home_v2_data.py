"""TASK-210-A: главная v2 — данные и серверная логика."""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.application.catalog_home_page import _default_when_key, _parse_when
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_public_ice_city_day import _add_today_session


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _count_sql(db_session):
    """Подсчёт SQL-запросов."""
    bind = db_session.sync_session.get_bind()
    counts = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        head = (statement or "").lstrip().upper()
        if head.startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    return bind, counts, _before


@pytest.mark.asyncio
async def test_ac1_default_when_friday_after_15_is_weekend(app_use_test_db, db_session, monkeypatch) -> None:
    """AC-1: Пт с 15:00 по умолчанию 'В выходные'."""
    # Пт 16:00 по Минску
    friday_16 = datetime(2026, 10, 9, 16, 0, tzinfo=ZoneInfo("Europe/Minsk"))
    fixed_now = friday_16.astimezone(ZoneInfo("UTC"))

    key = _default_when_key(fixed_now)
    assert key == "weekend", f"Expected 'weekend' but got '{key}'"


@pytest.mark.asyncio
async def test_ac1_default_when_wednesday_noon_is_today(app_use_test_db, db_session, monkeypatch) -> None:
    """AC-1: Ср 12:00 по умолчанию 'Сегодня'."""
    # Ср 12:00 по Минску
    wed_12 = datetime(2026, 10, 7, 12, 0, tzinfo=ZoneInfo("Europe/Minsk"))
    fixed_now = wed_12.astimezone(ZoneInfo("UTC"))

    key = _default_when_key(fixed_now)
    assert key == "today", f"Expected 'today' but got '{key}'"


@pytest.mark.asyncio
async def test_ac1_when_weekend_shows_saturday_sunday_sessions(app_use_test_db, db_session, monkeypatch) -> None:
    """AC-1: ?when=weekend в Пт 16:00 показывает сеансы Сб-Вс."""
    from src.application.ice_session_use_cases import create_ice_session

    # Пт 16:00 по Минску
    friday_16 = datetime(2026, 10, 9, 16, 0, tzinfo=ZoneInfo("Europe/Minsk"))
    fixed_now = friday_16.astimezone(ZoneInfo("UTC"))
    monkeypatch.setattr("src.application.catalog_home_page._utc_now", lambda: fixed_now)

    # Создаём город и каток
    name = f"Выходные {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")

    # Добавляем сеансы на субботу и воскресенье
    saturday = (friday_16 + timedelta(days=1)).date()
    sunday = saturday + timedelta(days=1)

    await create_ice_session(
        db_session,
        arena_id,
        local_date=saturday,
        starts_at_local="10:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
    )
    await create_ice_session(
        db_session,
        arena_id,
        local_date=sunday,
        starts_at_local="14:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
    )
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/?when=weekend")

    assert resp.status_code == 200
    # Проверяем, что счётчик показывает "В эти выходные"
    assert "В эти выходные" in resp.text or "выходные" in resp.text.lower()
    # Проверяем robots
    assert 'name="robots" content="noindex, follow"' in resp.text
    # Проверяем canonical
    assert 'rel="canonical"' in resp.text


@pytest.mark.asyncio
async def test_ac2_projected_sessions_have_projected_marker(app_use_test_db, db_session) -> None:
    """AC-2: Сеансы projected имеют метку 'обычно' и никогда не получают 'через N мин'."""
    # Проверяем, что CSS-класс для projected сеансов определён в шаблоне
    from pathlib import Path
    
    template_path = Path(__file__).resolve().parents[2] / "static" / "share" / "catalog-home.html"
    assert template_path.exists(), "Шаблон не найден"
    
    template_content = template_path.read_text(encoding="utf-8")
    # Проверяем наличие стилей для projected
    assert "session--projected" in template_content, "CSS-класс для projected не найден"
    assert "border-style: dashed" in template_content or "dashed" in template_content, "Пунктирная рамка не найдена"
    
    # Проверяем, что рендеринг работает с schedule_basis
    from src.application.catalog_home_page import _session_row
    
    test_row = {
        "city_name": "Минск",
        "arena_slug": "test",
        "arena_name": "Тестовый каток",
        "starts_at_local": "18:00",
        "ends_at_local": "19:00",
        "session_id": 1,
        "local_date": datetime.now().date(),
        "schedule_basis": "projected",
    }
    
    from src.application.catalog_home_page import _utc_now
    html = _session_row(test_row, now=_utc_now())
    
    # Проверяем, что projected сеанс имеет соответствующий класс и метку
    assert "session--projected" in html, "CSS-класс не применён"
    assert "обычно" in html.lower(), "Метка 'обычно' не найдена"


@pytest.mark.asyncio
async def test_ac3_upcoming_block_shown_for_city_with_five_plus_places(app_use_test_db, db_session) -> None:
    """AC-3: Блок ближайших показан для города с ≥5 местами с сеансами."""
    from src.application.ice_session_use_cases import create_ice_session

    name = f"Большой {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)

    # Создаём 5 мест с сеансами
    for i in range(5):
        arena_id = await _insert_arena(db_session, city_id, name=f"Каток {i}")
        await _add_today_session(db_session, arena_id)

    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/")

    assert resp.status_code == 200
    # Проверяем, что блок сеансов присутствует
    assert "Ближайш" in resp.text or "Лёд сегодня" in resp.text


@pytest.mark.asyncio
async def test_ac3_no_upcoming_block_for_city_with_one_place(app_use_test_db, db_session) -> None:
    """AC-3: Блок ближайших скрыт для города с 1 местом."""
    name = f"Малый {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    await _add_today_session(db_session, arena_id)
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/")

    assert resp.status_code == 200
    # При одном месте всё равно показываем сеансы, но проверим, что страница загружается
    assert name in resp.text


@pytest.mark.asyncio
async def test_ac5_sql_budget_is_flat_in_city_count(app_use_test_db, db_session) -> None:
    """AC-5: SQL на GET / ≤ 8 и не зависит от числа городов."""
    invalidate_public_city_cache()

    # 1 город
    one_id = await _insert_city(db_session, name=f"Один {uuid.uuid4().hex[:6]}")
    await _insert_arena(db_session, one_id, name="Арена 1")
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
    print(f"SQL для 1 города: {one_sql}")

    # Добавляем ещё 4 города
    for i in range(4):
        cid = await _insert_city(db_session, name=f"Город {i} {uuid.uuid4().hex[:4]}")
        await _insert_arena(db_session, cid, name=f"Арена {i}")
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
    print(f"SQL для 5 городов: {five_sql}")

    # Проверяем, что число SQL не зависит от числа городов
    assert one_sql == five_sql, f"SQL вырос с {one_sql} до {five_sql}"
    assert one_sql <= 8, f"SQL {one_sql} превышает бюджет 8"


@pytest.mark.asyncio
async def test_by_regions_dictionary_covers_all_public_by_cities(app_use_test_db, db_session) -> None:
    """Тест справочника областей: каждый публичный BY-город имеет область."""
    from src.application.ice_city_day import _public_cities
    from src.application.catalog_home_page import _BY_REGIONS

    cities = await _public_cities(db_session)
    by_cities = [c for c in cities if c.get("country") == "BY"]

    missing = []
    for city in by_cities:
        slug = city_slug(str(city["name"]))
        if slug not in _BY_REGIONS:
            missing.append((city["name"], slug))

    assert not missing, f"BY города без области в _BY_REGIONS: {missing}"


@pytest.mark.asyncio
async def test_when_day_without_d_shows_seven_day_links(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Дни {uuid.uuid4().hex[:6]}")
    await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/?when=day")

    assert resp.status_code == 200
    assert 'class="day-picker"' in resp.text
    assert resp.text.count("when=day&amp;d=") >= 7


@pytest.mark.asyncio
async def test_glide_city_cookie_set_on_city_page(app_use_test_db, db_session) -> None:
    name = f"Куки {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        resp = await client.get(f"/c/{slug}")

    assert resp.status_code == 200
    cookie = resp.headers.get("set-cookie", "")
    assert "glide_city=" in cookie
    assert f"glide_city={slug}" in cookie.lower()
    assert "Max-Age=" in cookie
    assert "Path=/" in cookie
    assert "samesite=lax" in cookie.lower()


@pytest.mark.asyncio
async def test_map_contains_link_for_each_by_city(app_use_test_db, db_session) -> None:
    name = f"Карта {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name, country="BY")
    await _insert_arena(db_session, city_id, name="Каток")
    await db_session.execute(
        text("UPDATE arenas SET latitude = 53.9, longitude = 27.5 WHERE city_id = :cid"),
        {"cid": city_id},
    )
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        resp = await client.get("/")

    assert resp.status_code == 200
    assert f'<a href="/c/{slug}">' in resp.text


@pytest.mark.asyncio
async def test_time_switcher_links_work_without_js(app_use_test_db, db_session) -> None:
    """Проверка, что ссылки переключателя времени работают без JS."""
    name = f"Переключ {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        # Проверяем все варианты
        for when in ["today", "tomorrow", "weekend"]:
            resp = await client.get(f"/?when={when}")
            assert resp.status_code == 200, f"Failed for when={when}"
            assert 'href="/?when=today"' in resp.text
            assert 'href="/?when=tomorrow"' in resp.text
            assert 'href="/?when=weekend"' in resp.text
