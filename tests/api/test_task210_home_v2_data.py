"""TASK-210-A: главная v2 — HTTP-проверки окон, счётчиков, блока и карты."""

from __future__ import annotations

import html as html_lib
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_public_ice_city_day import _add_today_session

_HOME_SQL_MAX = 8
_MINSK = ZoneInfo("Europe/Minsk")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _utc(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=_MINSK).astimezone(timezone.utc)


def _freeze(monkeypatch, moment: datetime) -> None:
    monkeypatch.setattr("src.application.catalog_home_page._utc_now", lambda: moment)


def _counter(html: str) -> str:
    match = re.search(r'<p class="[^"]*\bcounter\b[^"]*">([^<]*)</p>', html)
    assert match, "counter"
    return match.group(1)


def _city_li(html: str, city_name: str) -> str:
    for match in re.finditer(r'<li class="city">.*?</li>', html, re.S):
        if city_name in match.group(0):
            return match.group(0)
    raise AssertionError(city_name)


def _sessions_ul(html: str) -> str:
    match = re.search(r'<ul class="sessions">.*?</ul>', html, re.S)
    assert match, "sessions"
    return match.group(0)


def _session_li(html: str, arena_name: str) -> str:
    for match in re.finditer(r'<li class="session[^"]*">.*?</li>', html, re.S):
        if arena_name in match.group(0):
            return match.group(0)
    raise AssertionError(arena_name)


def _count_sql(db_session):
    bind = db_session.sync_session.get_bind()
    counts = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        head = (statement or "").lstrip().upper()
        if head.startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    return bind, counts, _before


async def _session(db_session, arena_id: int, day: date, starts: str, **kwargs) -> int:
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=day,
        starts_at_local=starts,
        duration_minutes=60,
        kind=kwargs.pop("kind", "public_skate"),
        price_adult_minor=kwargs.pop("price_adult_minor", 500),
        price_rental_minor=kwargs.pop("price_rental_minor", None),
    )
    return int(created["id"])


async def _basis(db_session, session_id: int, basis: str) -> None:
    await db_session.execute(
        text("UPDATE ice_sessions SET schedule_basis = :basis WHERE id = :id"),
        {"basis": basis, "id": session_id},
    )


async def _parser_job(db_session, arena_id: int, *, last_ok_at: datetime) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at,
                                         config, created_at, last_ok_at)
            VALUES (:aid, 'home_fresh_v1', true, 'daily', now(), '{}'::jsonb,
                    now() - interval '30 days', :ok)
            """
        ),
        {"aid": arena_id, "ok": last_ok_at},
    )


@pytest.mark.asyncio
async def test_ac1_weekend_count_excludes_friday_and_sunday_evening_rolls_forward(
    app_use_test_db, db_session, monkeypatch
) -> None:
    friday = _utc(2026, 10, 9, 16)
    _freeze(monkeypatch, friday)
    name = f"Выходные {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    await _session(db_session, arena_id, date(2026, 10, 9), "18:00")
    await _session(db_session, arena_id, date(2026, 10, 10), "10:00")
    await _session(db_session, arena_id, date(2026, 10, 11), "14:00")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        explicit = await client.get("/?when=weekend")
        default = await client.get("/")
        wednesday = _utc(2026, 10, 7, 12)
        _freeze(monkeypatch, wednesday)
        midweek_city = await _insert_city(db_session, name=f"Среда {uuid.uuid4().hex[:6]}")
        midweek_arena = await _insert_arena(db_session, midweek_city, name="Дневной")
        await _session(db_session, midweek_arena, date(2026, 10, 7), "18:00")
        await db_session.commit()
        invalidate_public_city_cache()
        midweek = await client.get("/")

    assert explicit.status_code == 200
    assert _counter(explicit.text) == "В эти выходные в Беларуси 2 сеанса в 1 городе"
    assert _counter(default.text) == "В эти выходные в Беларуси 2 сеанса в 1 городе"
    assert 'name="robots" content="noindex, follow"' in explicit.text
    assert 'rel="canonical"' in explicit.text
    assert _counter(midweek.text) == "Сегодня в Беларуси 1 сеанс в 1 городе"

    sunday = _utc(2026, 10, 11, 19)
    _freeze(monkeypatch, sunday)
    late_name = f"Позднее {uuid.uuid4().hex[:6]}"
    late_city = await _insert_city(db_session, name=late_name)
    late_arena = await _insert_arena(db_session, late_city, name="Воскресный")
    await _session(db_session, late_arena, date(2026, 10, 11), "20:00")
    await _session(db_session, late_arena, date(2026, 10, 17), "11:00")
    await _session(db_session, late_arena, date(2026, 10, 17), "13:00")
    await db_session.commit()
    invalidate_public_city_cache()
    async with _client() as client:
        rolled = await client.get("/")
    # Без сдвига на следующие выходные в окне остаётся только вс 20:00 — это 1, а не 2.
    assert _counter(rolled.text) == "В эти выходные в Беларуси 2 сеанса в 1 городе"


@pytest.mark.asyncio
async def test_ac2_minutes_until_is_in_html_only_for_live_under_two_hours(
    app_use_test_db, db_session, monkeypatch
) -> None:
    moment = _utc(2026, 10, 7, 12)
    _freeze(monkeypatch, moment)
    name = f"Минуты {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    soon_id = await _insert_arena(db_session, city_id, name="Живой скоро")
    projected_id = await _insert_arena(db_session, city_id, name="Обычный каток")
    later_id = await _insert_arena(db_session, city_id, name="Живой позже")
    await _insert_arena(db_session, city_id, name="Запас один")
    await _insert_arena(db_session, city_id, name="Запас два")
    soon = await _session(
        db_session, soon_id, date(2026, 10, 7), "12:30", price_adult_minor=1000, price_rental_minor=500
    )
    projected = await _session(db_session, projected_id, date(2026, 10, 7), "12:40")
    later = await _session(db_session, later_id, date(2026, 10, 7), "15:00")
    for arena_id, start in (
        (await _arena_id(db_session, city_id, "Запас один"), "16:00"),
        (await _arena_id(db_session, city_id, "Запас два"), "17:00"),
    ):
        await _session(db_session, arena_id, date(2026, 10, 7), start)
    await _basis(db_session, soon, "live")
    await _basis(db_session, projected, "projected")
    await _basis(db_session, later, "live")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        resp = await client.get("/", cookies={"glide_city": slug})
    assert resp.status_code == 200
    live = _session_li(resp.text, "Живой скоро")
    usual = _session_li(resp.text, "Обычный каток")
    far = _session_li(resp.text, "Живой позже")
    assert "через 30 мин" in live
    assert "с прокатом 15 BYN" in live
    assert "12:30–13:30" in live
    assert "12:30:00" not in live
    assert "через" not in usual
    assert "обычно" in usual
    assert "по обычной сетке катка — лучше уточнить" in usual
    assert "через" not in far


async def _arena_id(db_session, city_id: int, name: str) -> int:
    return int(
        (
            await db_session.execute(
                text("SELECT id FROM arenas WHERE city_id = :cid AND name = :name"),
                {"cid": city_id, "name": name},
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_ac3_upcoming_block_follows_cookie_and_place_threshold(app_use_test_db, db_session, monkeypatch) -> None:
    _freeze(monkeypatch, _utc(2026, 10, 7, 12))
    big = f"Большой {uuid.uuid4().hex[:6]}"
    small = f"Малый {uuid.uuid4().hex[:6]}"
    big_id = await _insert_city(db_session, name=big)
    small_id = await _insert_city(db_session, name=small)
    for i in range(5):
        arena_id = await _insert_arena(db_session, big_id, name=f"Каток {i}")
        await _session(db_session, arena_id, date(2026, 10, 7), "18:00")
    small_arena = await _insert_arena(db_session, small_id, name="Один каток")
    await _session(db_session, small_arena, date(2026, 10, 7), "18:00")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        shown = await client.get("/", cookies={"glide_city": city_slug(big)})
        hidden = await client.get("/", cookies={"glide_city": city_slug(small)})
    assert shown.status_code == 200
    assert f"Ближайшие в {big}" in shown.text
    assert 'class="sessions"' in shown.text
    assert hidden.status_code == 200
    assert f"Ближайшие в {small}" not in hidden.text
    assert 'class="sessions"' not in hidden.text
    assert small in hidden.text


@pytest.mark.asyncio
async def test_ac4_by_cities_stay_on_the_map_and_ru_does_not(app_use_test_db, db_session, monkeypatch) -> None:
    """Карта в HTML ещё не рисуется (210-B); проверяем view-model SVG + ссылки в списке городов."""
    from src.application.catalog_home_page import load_catalog_home_view

    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY,RU")
    brest = await _insert_city(db_session, name="Брест", country="BY")
    bobruysk = await _insert_city(db_session, name="Бобруйск", country="BY")
    grodno = await _insert_city(db_session, name="Гродно", country="BY")
    ru = await _insert_city(db_session, name="Тверь", country="RU")
    await _insert_arena(db_session, brest, name="Брест без точки", latitude=None, longitude=None)
    await _insert_arena(db_session, bobruysk, name="Бобруйск без точки", latitude=None, longitude=None)
    await _insert_arena(db_session, grodno, name="Гродно с точкой", latitude=53.669, longitude=23.829)
    await _insert_arena(db_session, ru, name="Тверь с точкой", latitude=56.86, longitude=35.91)
    await db_session.commit()
    invalidate_public_city_cache()

    view = await load_catalog_home_view(db_session)
    svg = str(view.get("map_svg") or "")
    assert 'class="home-map"' in svg
    assert 'href="/c/brest"' in svg
    assert 'href="/c/bobruysk"' in svg
    assert 'href="/c/grodno"' in svg
    assert 'href="/c/tver"' not in svg

    async with _client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert 'class="home-map"' not in resp.text
    assert 'href="/c/brest"' in resp.text
    assert 'href="/c/bobruysk"' in resp.text
    assert 'href="/c/grodno"' in resp.text
    assert 'href="/c/tver"' in resp.text


@pytest.mark.asyncio
async def test_ac5_sql_budget_on_upcoming_path_with_cookie(app_use_test_db, db_session, monkeypatch) -> None:
    _freeze(monkeypatch, _utc(2026, 10, 7, 12))
    name = f"Бюджет {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    for i in range(5):
        arena_id = await _insert_arena(db_session, city_id, name=f"Арена {i}")
        await _session(db_session, arena_id, date(2026, 10, 7), "18:00")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    bind, counts, before = _count_sql(db_session)
    try:
        async with _client() as client:
            one = await client.get("/", cookies={"glide_city": slug})
        one_sql = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", before)
    assert one.status_code == 200
    assert 'class="sessions"' in one.text

    for i in range(4):
        extra = await _insert_city(db_session, name=f"Ещё {i} {uuid.uuid4().hex[:4]}")
        await _insert_arena(db_session, extra, name=f"Площадка {i}")
    await db_session.commit()
    invalidate_public_city_cache()

    bind, counts, before = _count_sql(db_session)
    try:
        async with _client() as client:
            five = await client.get("/", cookies={"glide_city": slug})
        five_sql = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", before)
    assert five.status_code == 200
    assert one_sql == five_sql
    assert one_sql <= _HOME_SQL_MAX


@pytest.mark.asyncio
async def test_today_counter_matches_ice_page_without_closed_or_very_stale(app_use_test_db, db_session) -> None:
    name = f"Счётчик {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    normal = await _insert_arena(db_session, city_id, name="Живой каток")
    closed = await _insert_arena(db_session, city_id, name="Закрытый каток")
    stale = await _insert_arena(db_session, city_id, name="Старый каток")
    await _add_today_session(db_session, normal)
    await _add_today_session(db_session, closed)
    await _add_today_session(db_session, stale)
    await db_session.execute(
        text("UPDATE arena_profiles SET schedule_mode = 'season_closed' WHERE arena_id = :id"),
        {"id": closed},
    )
    await _parser_job(db_session, stale, last_ok_at=datetime.now(timezone.utc) - timedelta(days=5))
    await db_session.execute(
        text("UPDATE ice_sessions SET observed_at = :observed WHERE arena_id = :id"),
        {"observed": datetime.now(timezone.utc) - timedelta(days=5), "id": stale},
    )
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        home = await client.get("/?when=today")
        ice = await client.get(f"/ice/{slug}/today")
    assert home.status_code == 200
    assert ice.status_code == 200
    from src.application.catalog_home_page import parse_city_session_count_from_home

    assert parse_city_session_count_from_home(home.text, name) == 1
    assert re.search(r"1 сеанс на ", ice.text)


@pytest.mark.asyncio
async def test_all_link_uses_selection_when_and_day_page_only_for_today(
    app_use_test_db, db_session, monkeypatch
) -> None:
    _freeze(monkeypatch, _utc(2026, 10, 9, 16))
    name = f"Ссылки {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_ids = [await _insert_arena(db_session, city_id, name=f"Лёд {i}") for i in range(5)]
    for arena_id in arena_ids:
        await _session(db_session, arena_id, date(2026, 10, 10), "12:00")
        await _session(db_session, arena_id, date(2026, 10, 13), "12:00")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        weekend = await client.get("/?when=weekend", cookies={"glide_city": slug})
        tomorrow = await client.get("/?when=tomorrow", cookies={"glide_city": slug})
        today = await client.get("/?when=today", cookies={"glide_city": slug})
        day = await client.get("/?when=day&d=2026-10-13", cookies={"glide_city": slug})
        today_day = await client.get("/?when=day&d=2026-10-09", cookies={"glide_city": slug})
    assert f'href="/c/{slug}?w=weekend"' in weekend.text
    assert f'href="/c/{slug}?w=tomorrow"' in tomorrow.text
    assert f'href="/c/{slug}?w=today"' in today.text
    assert "Все →" not in day.text
    assert f'href="/ice/{slug}/today"' in today_day.text


@pytest.mark.asyncio
async def test_ohm_chip_stays_hidden_and_bad_day_falls_back_to_today(app_use_test_db, db_session, monkeypatch) -> None:
    _freeze(monkeypatch, _utc(2026, 10, 7, 12))
    name = f"День {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    await _session(db_session, arena_id, date(2026, 10, 7), "18:00")
    await _session(db_session, arena_id, date(2026, 10, 14), "18:00")
    await _session(db_session, arena_id, date(2026, 10, 8), "19:00", kind="hockey_practice")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        bad = await client.get("/?when=day&d=2026-10-14")
        picker = await client.get("/?when=day")
    assert "Хоккей (ОХМ)" not in bad.text
    assert "kind=ohm" not in bad.text
    assert "лыжероллер" not in bad.text.lower()
    assert _counter(bad.text) == "Сегодня в Беларуси 1 сеанс в 1 городе"
    assert 'class="day-picker"' not in bad.text
    assert bad.text.count("when=day&amp;d=") == 0
    assert 'class="day-picker"' in picker.text
    assert picker.text.count("when=day&amp;d=") >= 7


@pytest.mark.asyncio
async def test_glide_city_cookie_set_on_city_and_place_pages(app_use_test_db, db_session) -> None:
    name = f"Куки {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    arena_slug = (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
    ).scalar_one()

    async with _client() as client:
        city_page = await client.get(f"/c/{slug}")
        place_page = await client.get(f"/p/{slug}/{arena_slug}")
    for resp, label in ((city_page, "city"), (place_page, "place")):
        assert resp.status_code == 200, label
        cookie = resp.headers.get("set-cookie", "")
        assert f"glide_city={slug}" in cookie.lower()
        assert "Max-Age=" in cookie
        assert "Path=/" in cookie
        assert "samesite=lax" in cookie.lower()
        assert "httponly" in cookie.lower()


@pytest.mark.asyncio
async def test_when_query_works_without_js_switcher(app_use_test_db, db_session) -> None:
    """Свитчер в HTML — 210-B; здесь только что ``?when=`` принимается и ставит noindex."""
    name = f"Переключ {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        for when in ("today", "tomorrow", "weekend"):
            resp = await client.get(f"/?when={when}")
            assert resp.status_code == 200, when
            assert 'name="robots" content="noindex, follow"' in resp.text
            assert 'rel="canonical"' in resp.text


@pytest.mark.asyncio
async def test_friday_default_city_row_does_not_say_today(app_use_test_db, db_session, monkeypatch) -> None:
    _freeze(monkeypatch, _utc(2026, 10, 9, 16))
    name = f"Пятница {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Субботний")
    await _session(db_session, arena_id, date(2026, 10, 10), "12:00")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    row = _city_li(resp.text, name)
    assert "сегодня" not in row
    assert "в выходные" in row
    assert "/ice/" not in row


@pytest.mark.asyncio
async def test_counter_ignores_ru_sessions(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY,RU")
    _freeze(monkeypatch, _utc(2026, 10, 7, 12))
    by_name = f"Только BY {uuid.uuid4().hex[:6]}"
    ru_name = f"Только RU {uuid.uuid4().hex[:6]}"
    by_id = await _insert_city(db_session, name=by_name, country="BY")
    ru_id = await _insert_city(db_session, name=ru_name, country="RU")
    by_arena = await _insert_arena(db_session, by_id, name="Белорусский")
    ru_arena = await _insert_arena(db_session, ru_id, name="Российский")
    await _session(db_session, by_arena, date(2026, 10, 7), "18:00")
    await _session(db_session, ru_arena, date(2026, 10, 7), "18:00")
    await _session(db_session, ru_arena, date(2026, 10, 7), "19:00")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/")
    assert _counter(resp.text) == "Сегодня в Беларуси 1 сеанс в 1 городе"


@pytest.mark.asyncio
async def test_single_place_city_button_opens_the_place(app_use_test_db, db_session, monkeypatch) -> None:
    """Кнопка города в HTML — 210-B; проверяем href в view-model."""
    from src.application.catalog_home_page import load_catalog_home_view

    _freeze(monkeypatch, _utc(2026, 10, 7, 12))
    name = f"Одно место {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Единственный")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    arena_slug = (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
    ).scalar_one()

    view = await load_catalog_home_view(db_session, user_city_slug=slug, now=_utc(2026, 10, 7, 12))
    assert view["user_city"] is not None
    assert view["user_city"]["href"] == f"/p/{slug}/{arena_slug}"

    async with _client() as client:
        resp = await client.get("/", cookies={"glide_city": slug})
    assert resp.status_code == 200
    assert 'class="city-button"' not in resp.text


@pytest.mark.asyncio
async def test_upcoming_cards_are_the_selected_window_without_stale_or_closed(
    app_use_test_db, db_session, monkeypatch
) -> None:
    _freeze(monkeypatch, _utc(2026, 10, 9, 16))
    name = f"Окно {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    friday = await _insert_arena(db_session, city_id, name="Пятничный каток")
    stale = await _insert_arena(db_session, city_id, name="Старый каток")
    closed = await _insert_arena(db_session, city_id, name="Закрытый каток")
    early = await _insert_arena(db_session, city_id, name="Суббота ранняя")
    for i, start in enumerate(("13:00", "14:00", "15:00", "16:00")):
        arena_id = await _insert_arena(db_session, city_id, name=f"Суббота {i}")
        await _session(db_session, arena_id, date(2026, 10, 10), start)
    await _session(db_session, friday, date(2026, 10, 9), "18:00")
    await _session(db_session, early, date(2026, 10, 10), "12:00")
    stale_session = await _session(db_session, stale, date(2026, 10, 10), "08:00")
    await _session(db_session, closed, date(2026, 10, 10), "09:00")
    await _basis(db_session, stale_session, "live")
    await _parser_job(db_session, stale, last_ok_at=datetime(2026, 10, 4, 12, tzinfo=timezone.utc))
    await db_session.execute(
        text("UPDATE ice_sessions SET observed_at = :observed WHERE arena_id = :id"),
        {"observed": datetime(2026, 10, 4, 12, tzinfo=timezone.utc), "id": stale},
    )
    await db_session.execute(
        text("UPDATE arena_profiles SET schedule_mode = 'season_closed' WHERE arena_id = :id"),
        {"id": closed},
    )
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/?when=weekend", cookies={"glide_city": city_slug(name)})
    assert resp.status_code == 200
    block = _sessions_ul(resp.text)
    assert "Суббота ранняя" in block
    assert "Пятничный каток" not in block
    assert "Старый каток" not in block
    assert "Закрытый каток" not in block


_HREF_RE = re.compile(r'href="([^"]*)"')


def _internal_hrefs(page: str) -> set[str]:
    found: set[str] = set()
    for raw in _HREF_RE.findall(page):
        href = html_lib.unescape(raw).strip()
        if not href.startswith("/") or href.startswith("//"):
            continue
        found.add(href)
    return found


@pytest.mark.asyncio
async def test_home_does_not_link_first_time_until_the_page_exists(app_use_test_db, db_session, monkeypatch) -> None:
    _freeze(monkeypatch, _utc(2026, 10, 7, 12))
    name = f"Чипы {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток чипа")
    await _session(db_session, arena_id, date(2026, 10, 7), "18:00")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert 'href="/first-time"' not in resp.text
    assert "Первый раз" not in resp.text


@pytest.mark.asyncio
async def test_home_internal_hrefs_resolve(app_use_test_db, db_session, monkeypatch) -> None:
    _freeze(monkeypatch, _utc(2026, 10, 7, 12))
    name = f"Ссылки {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    for i, start in enumerate(("14:00", "15:00", "16:00", "17:00", "18:00")):
        arena_id = await _insert_arena(db_session, city_id, name=f"Каток ссылок {i}")
        await _session(db_session, arena_id, date(2026, 10, 7), start)
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    hrefs: set[str] = set()

    async with _client() as client:
        for when in ("today", "tomorrow", "weekend", "day"):
            for cookies in ({"glide_city": slug}, None):
                resp = await client.get(f"/?when={when}", cookies=cookies)
                assert resp.status_code == 200, when
                hrefs |= _internal_hrefs(resp.text)
        assert hrefs, "home page has no internal hrefs"
        assert "/first-time" not in hrefs
        assert any(href.startswith("/c/") for href in hrefs)
        assert any(href.startswith("/p/") for href in hrefs)
        broken: list[str] = []
        for href in sorted(hrefs):
            followed = await client.get(href)
            if followed.status_code not in range(200, 400):
                broken.append(f"{followed.status_code} {href}")
    assert not broken, broken


@pytest.mark.asyncio
async def test_upcoming_cards_stay_inside_today_window_not_the_seven_day_horizon(
    app_use_test_db, db_session, monkeypatch
) -> None:
    _freeze(monkeypatch, _utc(2026, 10, 7, 12))
    name = f"Горизонт {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    today_early = await _insert_arena(db_session, city_id, name="Сегодня ранний")
    today_late = await _insert_arena(db_session, city_id, name="Сегодня поздний")
    tomorrow = await _insert_arena(db_session, city_id, name="Завтра за окном")
    later = await _insert_arena(db_session, city_id, name="Пятница за окном")
    filler = await _insert_arena(db_session, city_id, name="Суббота горизонта")
    await _session(db_session, today_early, date(2026, 10, 7), "14:00")
    await _session(db_session, today_late, date(2026, 10, 7), "18:00")
    await _session(db_session, tomorrow, date(2026, 10, 8), "10:00")
    await _session(db_session, later, date(2026, 10, 9), "12:00")
    await _session(db_session, filler, date(2026, 10, 10), "12:00")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/?when=today", cookies={"glide_city": city_slug(name)})
    assert resp.status_code == 200
    block = _sessions_ul(resp.text)
    assert "Сегодня ранний" in block
    assert "Сегодня поздний" in block
    assert "Завтра за окном" not in block
    assert "Пятница за окном" not in block
    assert "Суббота горизонта" not in block
