"""TASK-210-A: главная v2 — HTTP-проверки окон, счётчиков, блока и карты."""

from __future__ import annotations

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
    match = re.search(r'<p class="counter">([^<]*)</p>', html)
    assert match, "counter"
    return match.group(1)


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
    await db_session.commit()
    invalidate_public_city_cache()
    async with _client() as client:
        rolled = await client.get("/")
    assert _counter(rolled.text) == "В эти выходные в Беларуси 1 сеанс в 1 городе"


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
async def test_ac4_by_city_without_place_coordinates_stays_on_the_map(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name="Брест", country="BY")
    await _insert_arena(db_session, city_id, name="Без точки", latitude=None, longitude=None)
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    svg = re.search(r'<svg class="home-map".*?</svg>', resp.text, re.S)
    assert svg, "map"
    assert 'href="/c/brest"' in svg.group(0)


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
        day = await client.get("/?when=day&d=2026-10-13", cookies={"glide_city": slug})
        today_day = await client.get("/?when=day&d=2026-10-09", cookies={"glide_city": slug})
    assert f'href="/c/{slug}?w=weekend"' in weekend.text
    assert f'href="/c/{slug}?w=tomorrow"' in tomorrow.text
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


@pytest.mark.asyncio
async def test_time_switcher_links_work_without_js(app_use_test_db, db_session) -> None:
    name = f"Переключ {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        for when in ("today", "tomorrow", "weekend"):
            resp = await client.get(f"/?when={when}")
            assert resp.status_code == 200, when
            assert 'href="/?when=today"' in resp.text
            assert 'href="/?when=tomorrow"' in resp.text
            assert 'href="/?when=weekend"' in resp.text
