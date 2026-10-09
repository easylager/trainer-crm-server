"""TASK-224: /c/{город} без параметров — маршрутизатор потребностей; карта главной."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.catalog_home_page import (
    _BY_CITY_ROWS,
    _MAP_TAP_RADIUS_MAJOR,
    _OBLAST_CENTER_SLUGS,
    _map_project,
    build_map_points,
    map_point_inside_country,
    render_map_svg,
)
from src.application.city_hub_page import hot_window_key, open_state
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_time_windows import resolve_window
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _session(db_session, arena_id: int, *, day: date, hhmm: str, kind: str = "public_skate") -> int:
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=day,
        starts_at_local=hhmm,
        duration_minutes=60,
        kind=kind,
        price_adult_minor=1200,
    )
    await db_session.flush()
    return int(created["id"])


def _route(html: str, name: str) -> str:
    for match in re.finditer(r'<article class="route">.*?</article>', html, re.S):
        if f'<span class="name">{name}</span>' in match.group(0):
            return match.group(0)
    return ""


def _minsk_today() -> date:
    return datetime.now(ZoneInfo("Europe/Minsk")).date()


def _weekend_days_ahead() -> list[date]:
    """Дни окна «Сб–Вс» списка (resolve_window), начиная с завтра по Минску.

    Сегодняшние сеансы в тест не кладём. ``date.today()`` на раннере — UTC, и в
    субботу по Минску субботний сеанс уже попадает в «Сегодня».
    """
    tw = resolve_window("weekend", datetime.now(timezone.utc))
    assert tw is not None
    tz = ZoneInfo("Europe/Minsk")
    start = tw.starts_at.astimezone(tz).date()
    end = tw.ends_at.astimezone(tz).date()  # понедельник, не включительно
    tomorrow = _minsk_today() + timedelta(days=1)
    return [start + timedelta(days=i) for i in range((end - start).days) if start + timedelta(days=i) >= tomorrow]


# ---------------------------------------------------------------------------
# Карта
# ---------------------------------------------------------------------------


def test_map_boundary_contains_every_directory_city() -> None:
    """AC-004: все города справочника — внутри контура страны, а не в Литве или Польше."""
    outside = []
    for name, _region, lat, lon in _BY_CITY_ROWS:
        x, y = _map_project(lat, lon)
        if not map_point_inside_country(x, y):
            outside.append(name)
    assert outside == []


def test_map_svg_links_every_city_with_tap_zone_and_ohm_ring() -> None:
    cities = [
        {"id": 1, "name": "Минск", "slug": "minsk", "country": "BY", "avg_lat": 53.9, "avg_lon": 27.56,
         "place_count": 20, "session_count": 5, "has_ohm": True},
        {"id": 2, "name": "Горки", "slug": "gorki", "country": "BY", "avg_lat": 54.27, "avg_lon": 30.99,
         "place_count": 1, "session_count": 0, "has_ohm": False},
        {"id": 3, "name": "Санкт-Петербург", "slug": "spb", "country": "RU", "avg_lat": 59.9, "avg_lon": 30.3,
         "place_count": 3, "session_count": 1, "has_ohm": True},
    ]
    points = build_map_points(cities)
    assert [p["slug"] for p in points] == ["minsk", "gorki"], "RU не на карте Беларуси"
    svg = render_map_svg(points)
    assert svg.count('class="home-map__city"') == 2
    assert 'href="/c/minsk"' in svg and 'href="/c/gorki"' in svg
    assert svg.count('class="home-map__tap"') == 2
    assert f'r="{_MAP_TAP_RADIUS_MAJOR:.1f}"' in svg, "областной центр — зона ≥ 44px"
    # Кольцо ОХМ только у Минска; подпись — только у областного центра.
    assert svg.count('stroke-dasharray="3 4"') == 1
    assert ">Минск</text>" in svg and ">Горки</text>" not in svg
    assert "minsk" in _OBLAST_CENTER_SLUGS


# ---------------------------------------------------------------------------
# Хаб города
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_city_hub_shows_only_tiles_with_data_and_quick_windows(app_use_test_db, db_session) -> None:
    """AC-002: плитки по данным; под «Покататься» и «ОХМ» — окна со счётчиками, нули — не ссылки."""
    name = f"Хабск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    ohm_rink = await _insert_arena(db_session, city_id, name=f"Арена ОХМ {uuid.uuid4().hex[:4]}")
    tomorrow = _minsk_today() + timedelta(days=1)
    weekend = _weekend_days_ahead()
    await _session(db_session, rink, day=tomorrow, hhmm="12:00")
    skate_weekend = 1 if tomorrow in weekend else 0
    if weekend:
        await _session(db_session, rink, day=weekend[-1], hhmm="13:00")
        skate_weekend += 1
    ohm_weekend = 0
    for n, day in enumerate(weekend):
        await _session(db_session, ohm_rink, day=day, hhmm=f"07:{n * 30:02d}", kind="hockey_practice")
        ohm_weekend += 1
    # ОХМ вне окна — чтобы «Все» было больше «Сб–Вс».
    await _session(db_session, ohm_rink, day=date.today() + timedelta(days=10), hhmm="06:45", kind="hockey_practice")
    ohm_all = ohm_weekend + 1
    skate_tomorrow = 1 + (1 if weekend and weekend[-1] == tomorrow else 0)
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        hub = await client.get(f"/c/{slug}")
        by_id = await client.get(f"/c/{city_id}")
    assert hub.status_code == 200
    html = hub.text
    assert f'<h1 class="hero__title">{name}</h1>' in html
    assert "Что нужно?" in html
    assert 'class="pick"' not in html, "хаб — не список мест"

    skate = _route(html, "Покататься")
    assert skate, html
    assert f'href="/c/{slug}?t=ice"' in skate
    assert "2 катка" in skate
    assert f'href="/c/{slug}?t=ice&amp;w=tomorrow"' in skate and f"Завтра <small>{skate_tomorrow}</small>" in skate
    if skate_weekend:
        assert f'href="/c/{slug}?t=ice&amp;w=weekend"' in skate and f"Сб–Вс <small>{skate_weekend}</small>" in skate
    assert "<span>Сегодня <small>0</small></span>" in skate, "ноль — не ссылка"
    assert "ближайший <b>завтра 12:00" in skate

    ohm = _route(html, "Хоккей")
    assert ohm, html
    assert f'href="/c/{slug}?kind=ohm"' in ohm and "1 каток" in ohm
    if ohm_weekend:
        assert f'href="/c/{slug}?w=weekend&amp;kind=ohm"' in ohm and f"Сб–Вс <small>{ohm_weekend}</small>" in ohm
        assert "07:00" in ohm
    else:
        assert "<span>Сб–Вс <small>0</small></span>" in ohm
    assert f"Все <small>{ohm_all}</small>" in ohm

    # Нет данных — нет плитки.
    assert not _route(html, "Заточка")
    assert not _route(html, "Магазины")
    assert not _route(html, "Тренеры")

    # «Ближайшее на льду» — ссылки на страницы мест; все места — списком (SEO).
    assert "Ближайшее на льду" in html
    assert f'href="/p/{slug}/' in html
    assert "Все места города" in html
    # Канон и редирект по id — как у подборки.
    assert by_id.status_code == 301 and by_id.headers["location"] == f"/c/{slug}"
    assert f'<link rel="canonical" href="http://test/c/{slug}"' in html or f"/c/{slug}" in html
    assert 'content="index, follow"' in html


@pytest.mark.asyncio
async def test_city_hub_service_and_shop_tiles_count_open_now(app_use_test_db, db_session) -> None:
    name = f"Заточинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    always_open = {"daily": {"open": "00:00", "close": "23:59"}}
    rink = await _insert_arena(db_session, city_id, name="Каток с заточкой", opening_hours=always_open)
    plain = await _insert_arena(db_session, city_id, name="Каток простой")
    shop = await _insert_arena(db_session, city_id, name="Магазин коньков", opening_hours=always_open)
    await db_session.execute(
        text("UPDATE arenas SET venue_type = 'shop' WHERE id = :id"), {"id": shop}
    )
    await db_session.execute(
        text("UPDATE arena_profiles SET amenities = '{\"skate_sharpening\": true}'::jsonb WHERE arena_id = :id"),
        {"id": rink},
    )
    await db_session.execute(
        text(
            "UPDATE arena_profiles SET amenities = '{\"skate_sharpening\": true, \"skate_rental\": true}'::jsonb "
            "WHERE arena_id = :id"
        ),
        {"id": shop},
    )
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        hub = await client.get(f"/c/{slug}")
    assert hub.status_code == 200
    html = hub.text
    service = _route(html, "Заточка")
    assert service, html
    assert f'href="/c/{slug}?svc=service"' in service
    assert "2 места" in service
    assert "<b>2 открыты сейчас</b>" in service
    shops = _route(html, "Магазины")
    assert shops and f'href="/c/{slug}?t=shop"' in shops
    assert "<b>1 открыто сейчас</b>" in shops
    assert not _route(html, "Покататься") or "Каток простой" not in _route(html, "Покататься")
    assert plain  # каток без сеансов — в «Все места города», но без плитки времени
    assert "Каток простой" in html


@pytest.mark.asyncio
async def test_city_hub_description_matches_selection_share(app_use_test_db, db_session) -> None:
    """og:description хаба = строка share API подборки: одна правда для превью и картинки."""
    name = f"Однаправда {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    for n in range(3):
        rink = await _insert_arena(db_session, city_id, name=f"Каток {n} {uuid.uuid4().hex[:4]}")
        if n < 2:
            await _session(db_session, rink, day=date.today() + timedelta(days=1 + n), hhmm="10:00")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    async with _client() as client:
        hub = await client.get(f"/c/{slug}")
        share = await client.get("/api/public/ice/selection/share", params={"city_id": city_id, "record": "false"})
    assert hub.status_code == 200 and share.status_code == 200
    og = re.search(r'<meta property="og:description" content="([^"]*)"', hub.text)
    assert og and og.group(1) == "3 катка · 2 сеанса"
    assert "3 катка · 2 сеанса" in share.json()["share_body"]


@pytest.mark.asyncio
async def test_city_hub_with_params_is_still_the_list(app_use_test_db, db_session) -> None:
    """AC-005: старые ссылки ведут на списки, хаб — только чистый /c/{город}."""
    name = f"Списочный {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await _session(db_session, rink, day=date.today() + timedelta(days=2), hhmm="11:00")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    async with _client() as client:
        weekend = await client.get(f"/c/{slug}", params={"w": "weekend"})
        ice = await client.get(f"/c/{slug}", params={"t": "ice"})
        paged = await client.get(f"/c/{slug}", params={"page": "1"})
        hub_src = await client.get(f"/c/{slug}", params={"src": "tg"})
    for resp in (weekend, ice, paged):
        assert resp.status_code == 200
        assert 'class="pick' in resp.text, "список мест"
        assert "Что нужно?" not in resp.text
    assert hub_src.status_code == 200 and "Что нужно?" in hub_src.text, "?src= — не фильтр"


def test_open_state_and_hot_window() -> None:
    minsk_noon = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)  # ср 12:00 по Минску
    hours = {"weekly": {"wed": ["10:00", "12:30"], "thu": ["10:00", "19:00"]}}
    assert open_state(hours, now=minsk_noon, tz_name="Europe/Minsk") == {"state": "soon", "close": "12:30"}
    assert open_state({"daily": {"open": "08:00", "close": "22:00"}}, now=minsk_noon, tz_name="Europe/Minsk")["state"] == "open"
    assert open_state({"weekly": {"thu": ["10:00", "19:00"]}}, now=minsk_noon, tz_name="Europe/Minsk")["state"] == "closed"
    assert open_state(None, now=minsk_noon, tz_name="Europe/Minsk")["state"] == "unknown"
    # Среда днём: по умолчанию «сегодня»; нет сеансов сегодня — следующее непустое окно.
    assert hot_window_key({"today": 3, "tomorrow": 5, "weekend": 7}, now=minsk_noon) == "today"
    assert hot_window_key({"today": 0, "tomorrow": 5, "weekend": 7}, now=minsk_noon) == "tomorrow"
    assert hot_window_key({"today": 0, "tomorrow": 0, "weekend": 0}, now=minsk_noon) is None
    friday_evening = datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc)  # пт 20:00 по Минску
    assert hot_window_key({"today": 1, "tomorrow": 5, "weekend": 7}, now=friday_evening) == "weekend"
