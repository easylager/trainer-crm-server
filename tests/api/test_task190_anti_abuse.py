"""TASK-190: боты вне метрик, доверенный IP, rate limit страниц/PNG, кэш PNG, open-telegram scope."""
from __future__ import annotations

import asyncio
import threading
import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.middleware.http_limits import reset_http_limiters_for_tests
from src.api.routes import public_ice_page
from src.application import ice_city_day_og
from src.application import png_render_cache as pc
from src.application.catalog_consumer_events import (
    KIND_PUBLIC_PAGE_VIEW,
    get_catalog_top_arenas_by_events,
    get_catalog_wau,
    public_actor_hash,
    record_catalog_consumer_event,
)
from src.application.ice_city_day import city_slug
from src.shared.client_ip import trusted_client_ip
from src.shared.ua_class import UA_CRAWLER, UA_HUMAN, UA_PREVIEW, UA_SEARCH, classify_user_agent

_SECRET = "test-catalog-actor-secret-0123456789abcdef"
_HUMAN_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _SECRET)
    monkeypatch.delenv("CATALOG_METRICS_COMPARABLE_SINCE", raising=False)
    reset_http_limiters_for_tests()
    pc.reset_png_cache_for_tests()
    yield
    reset_http_limiters_for_tests()
    pc.reset_png_cache_for_tests()


async def _city_arena(db_session) -> tuple[int, int, str]:
    name = f"Тест-190-{uuid.uuid4().hex[:6]}"
    city_id = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                "VALUES (:n, 'BY', 'default', true, 0) RETURNING id"
            ),
            {"n": name},
        )
    ).scalar_one()
    arena_id = (
        await db_session.execute(
            text(
                "INSERT INTO arenas (city_id, name, address, is_active, is_confirmed) "
                "VALUES (:c, 'Арена-190', 'ул. 1', true, true) RETURNING id"
            ),
            {"c": city_id},
        )
    ).scalar_one()
    await db_session.flush()
    return int(city_id), int(arena_id), name


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --- AC-1: боты -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ua,expected",
    [
        ("TelegramBot (like TwitterBot)", UA_PREVIEW),
        ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", UA_SEARCH),
        ("Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)", UA_SEARCH),
        ("Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)", UA_SEARCH),
        ("Mozilla/5.0 HeadlessChrome/120.0 Safari/537.36", UA_CRAWLER),
        ("python-requests/2.31", UA_CRAWLER),
        ("curl/8.4.0", UA_CRAWLER),
        ("SomethingSpider", UA_CRAWLER),
        ("", UA_CRAWLER),
        (None, UA_CRAWLER),
        (_HUMAN_UA, UA_HUMAN),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36", UA_HUMAN),
    ],
)
def test_classify_user_agent(ua, expected) -> None:
    assert classify_user_agent(ua) == expected


@pytest.mark.asyncio
async def test_page_views_store_class_not_ua(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "false")
    city_id, _, name = await _city_arena(db_session)
    uas = {
        "TelegramBot (like TwitterBot)": "1.1.1.1",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)": "1.1.1.2",
        "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)": "1.1.1.3",
        "Mozilla/5.0 (compatible; bingbot/2.0)": "1.1.1.4",
        "python-requests/2.31": "1.1.1.5",
        _HUMAN_UA: "1.1.1.6",
    }
    async with _client() as client:
        for ua, ip in uas.items():
            r = await client.get(
                f"/ice/{city_slug(name)}/today", headers={"user-agent": ua, "x-forwarded-for": ip}
            )
            assert r.status_code == 200, r.text
    rows = (
        await db_session.execute(
            text(
                "SELECT payload->>'ua_class', COUNT(*) FROM catalog_consumer_events "
                "WHERE city_id = :c AND kind = 'public_page_view' GROUP BY 1"
            ),
            {"c": city_id},
        )
    ).all()
    assert {r[0]: int(r[1]) for r in rows} == {"preview": 1, "search": 3, "crawler": 1, "human": 1}
    leaked = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM catalog_consumer_events WHERE city_id = :c AND payload::text ILIKE '%bot%'"),
            {"c": city_id},
        )
    ).scalar_one()
    assert leaked == 0, "raw UA must not be stored"


@pytest.mark.asyncio
async def test_wau_excludes_bot_rows_exactly(db_session) -> None:
    base = (await get_catalog_wau(db_session, days=7))["unique_actors"]
    for ua, cls in (("TelegramBot", "preview"), ("Googlebot", "search"), ("YandexBot", "search")):
        await record_catalog_consumer_event(
            db_session,
            kind=KIND_PUBLIC_PAGE_VIEW,
            surface="place_page",
            actor_hash=public_actor_hash(client_ip="9.9.9.9", user_agent=ua),
            payload={"ua_class": cls},
        )
    assert (await get_catalog_wau(db_session, days=7))["unique_actors"] == base
    await record_catalog_consumer_event(
        db_session,
        kind=KIND_PUBLIC_PAGE_VIEW,
        surface="place_page",
        actor_hash=public_actor_hash(client_ip="9.9.9.9", user_agent=_HUMAN_UA),
        payload={"ua_class": "human"},
    )
    assert (await get_catalog_wau(db_session, days=7))["unique_actors"] == base + 1


@pytest.mark.asyncio
async def test_top_arenas_excludes_bots(db_session) -> None:
    city_id, arena_id, _ = await _city_arena(db_session)
    await record_catalog_consumer_event(
        db_session,
        kind=KIND_PUBLIC_PAGE_VIEW,
        surface="place_page",
        actor_hash="a" * 64,
        city_id=city_id,
        arena_id=arena_id,
        payload={"ua_class": "preview"},
    )
    assert arena_id not in [t["arena_id"] for t in await get_catalog_top_arenas_by_events(db_session, days=7)]
    await record_catalog_consumer_event(
        db_session,
        kind=KIND_PUBLIC_PAGE_VIEW,
        surface="place_page",
        actor_hash="b" * 64,
        city_id=city_id,
        arena_id=arena_id,
        payload={"ua_class": "human"},
    )
    assert arena_id in [t["arena_id"] for t in await get_catalog_top_arenas_by_events(db_session, days=7)]


# --- AC-2: IP ---------------------------------------------------------------------------------


def test_trusted_client_ip_leftmost_public() -> None:
    f = trusted_client_ip
    assert f({"x-forwarded-for": "203.0.113.9, 7.7.7.7"}, "10.0.0.2") == "203.0.113.9"
    # внутренние / CGNAT / loopback / мусор пропускаются
    assert f({"x-forwarded-for": "100.64.0.5, 100.100.1.1, 10.1.1.1, 127.0.0.1, 198.51.100.7"}, "10.0.0.2") == "198.51.100.7"
    assert f({"x-forwarded-for": "garbage, 192.168.1.1, 2001:db8::1"}, None) == "2001:db8::1"
    # нет публичной записи в XFF -> X-Real-IP -> сокет
    assert f({"x-forwarded-for": "100.64.0.5", "x-real-ip": "198.51.100.8"}, "10.0.0.2") == "198.51.100.8"
    assert f({"x-forwarded-for": "garbage", "x-real-ip": "100.64.0.9"}, "172.16.0.3") == "172.16.0.3"
    assert f({"x-forwarded-for": "garbage"}, "10.0.0.2") == "10.0.0.2"
    assert f({}, "10.0.0.2") == "10.0.0.2"
    assert f({}, None) is None


def test_trusted_client_ip_rightmost_hops_fallback_strategy() -> None:
    h = {"x-forwarded-for": "6.6.6.6, 7.7.7.7, 203.0.113.9"}
    kw = {"strategy": "rightmost_hops"}
    assert trusted_client_ip(h, "10.0.0.2", hops=1, **kw) == "203.0.113.9"
    assert trusted_client_ip(h, "10.0.0.2", hops=2, **kw) == "7.7.7.7"
    assert trusted_client_ip(h, "10.0.0.2", hops=0, **kw) == "10.0.0.2"
    assert trusted_client_ip({"x-forwarded-for": "garbage"}, "10.0.0.2", hops=1, **kw) == "10.0.0.2"


@pytest.mark.asyncio
async def test_same_real_ip_is_one_actor_and_rate_limit_applies(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_PAGE_MAX_REQUESTS", "30")
    reset_http_limiters_for_tests()
    city_id, _, name = await _city_arena(db_session)
    statuses = []
    async with _client() as client:
        for _ in range(100):
            r = await client.get(
                f"/ice/{city_slug(name)}/today",
                headers={"user-agent": _HUMAN_UA, "x-forwarded-for": "203.0.113.50, 100.64.1.1"},
            )
            statuses.append(r.status_code)
    assert statuses.count(200) == 30
    assert statuses.count(429) == 70
    actors = (
        await db_session.execute(
            text(
                "SELECT COUNT(DISTINCT actor_hash) FROM catalog_consumer_events "
                "WHERE city_id = :c AND kind = 'public_page_view'"
            ),
            {"c": city_id},
        )
    ).scalar_one()
    assert actors == 1


@pytest.mark.asyncio
async def test_rightmost_strategy_ignores_spoofed_left_xff(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_IP_STRATEGY", "rightmost_hops")
    monkeypatch.setenv("API_RATE_LIMIT_PAGE_MAX_REQUESTS", "30")
    reset_http_limiters_for_tests()
    city_id, _, name = await _city_arena(db_session)
    statuses = []
    async with _client() as client:
        for n in range(60):
            r = await client.get(
                f"/ice/{city_slug(name)}/today",
                headers={"user-agent": _HUMAN_UA, "x-forwarded-for": f"198.51.100.{n}, 203.0.113.50"},
            )
            statuses.append(r.status_code)
    assert statuses.count(200) == 30 and statuses.count(429) == 30


@pytest.mark.asyncio
async def test_other_ip_is_not_limited_by_first(app_use_test_db, monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_PAGE_MAX_REQUESTS", "2")
    reset_http_limiters_for_tests()
    async with _client() as client:
        codes = [
            (
                await client.get("/c/nowhere", headers={"x-forwarded-for": "9.9.9.9", "user-agent": _HUMAN_UA})
            ).status_code
            for _ in range(3)
        ]
        other = await client.get("/c/nowhere", headers={"x-forwarded-for": "8.8.8.8", "user-agent": _HUMAN_UA})
    assert codes[-1] == 429
    assert other.status_code != 429


@pytest.mark.asyncio
async def test_preview_bot_has_wider_bucket_than_human(app_use_test_db, monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_PAGE_MAX_REQUESTS", "2")
    monkeypatch.setenv("API_RATE_LIMIT_BOT_MAX_REQUESTS", "50")
    reset_http_limiters_for_tests()
    async with _client() as client:
        codes = [
            (
                await client.get("/c/nowhere", headers={"x-forwarded-for": "9.9.9.9", "user-agent": "TelegramBot"})
            ).status_code
            for _ in range(10)
        ]
    assert 429 not in codes


@pytest.mark.asyncio
async def test_png_bucket_is_narrower(app_use_test_db, monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_IMAGE_MAX_REQUESTS", "3")
    reset_http_limiters_for_tests()
    async with _client() as client:
        codes = [
            (
                await client.get(
                    "/c/nowhere/og.png", headers={"x-forwarded-for": "9.9.9.9", "user-agent": _HUMAN_UA}
                )
            ).status_code
            for _ in range(6)
        ]
    assert codes[:3] == [404, 404, 404]
    assert codes[3:] == [429, 429, 429]


# --- AC-3: PNG --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_og_random_params_hit_cache_and_render_off_loop(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "false")
    _, _, name = await _city_arena(db_session)
    loop_thread = threading.get_ident()
    seen_threads: list[int] = []
    real = ice_city_day_og.render_ice_city_day_og

    def slow_render(**kw):
        seen_threads.append(threading.get_ident())
        time.sleep(0.4)
        return real(**kw)

    monkeypatch.setattr(public_ice_page, "render_ice_city_day_og", slow_render)
    url = f"/ice/{city_slug(name)}/today/og.png"
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    t = asyncio.create_task(ticker())
    async with _client() as client:
        first = await client.get(url, params={"cb": "a"})
        ticks_during_first = ticks
        rest = [await client.get(url, params={"cb": uuid.uuid4().hex, "x": str(i)}) for i in range(20)]
    t.cancel()
    assert first.status_code == 200 and first.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert all(r.content == first.content for r in rest)
    assert len(seen_threads) == 1, "random cache-busting params must not re-render"
    assert seen_threads[0] != loop_thread
    assert ticks_during_first >= 5, "event loop was blocked during the render"
    stats = pc.png_cache_stats()
    assert stats["renders"] == 1 and stats["hits"] == 20


@pytest.mark.asyncio
async def test_png_cache_key_changes_with_data() -> None:
    calls = []

    def render(x):
        calls.append(x)
        return b"png" + bytes([x])

    a = await pc.render_png_cached("k", {"p": 1}, {"v": 1}, render, 1)
    b = await pc.render_png_cached("k", {"p": 1}, {"v": 1}, render, 1)
    c = await pc.render_png_cached("k", {"p": 1}, {"v": 2}, render, 2)
    assert a == b and c != a and calls == [1, 2]


@pytest.mark.asyncio
async def test_png_cache_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(pc, "MAX_ENTRIES", 3)
    for i in range(10):
        await pc.render_png_cached("k", {"i": i}, None, lambda: b"x" * 10)
    assert pc.png_cache_stats()["entries"] == 3


# --- open-telegram scope ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_telegram_scope_comes_from_startapp(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "false")
    city_id, arena_id, _ = await _city_arena(db_session)
    other_city, other_arena, _ = await _city_arena(db_session)
    async with _client() as client:
        r = await client.get(
            "/api/public/catalog/open-telegram",
            params={
                "startapp": f"arena_{arena_id}",
                "surface": "place_page",
                "city_id": other_city,
                "arena_id": other_arena,
            },
            headers={"user-agent": "TelegramBot", "x-forwarded-for": "5.5.5.5"},
            follow_redirects=False,
        )
        ok = await client.get(
            "/api/public/catalog/open-telegram",
            params={"startapp": f"catalog_{city_id}", "surface": "selection_page", "city_id": city_id},
            headers={"user-agent": _HUMAN_UA, "x-forwarded-for": "5.5.5.6"},
            follow_redirects=False,
        )
    assert r.status_code == 302 and ok.status_code == 302
    rows = (
        await db_session.execute(
            text(
                "SELECT city_id, arena_id, (payload->>'scope_mismatch')::boolean, payload->>'ua_class' "
                "FROM catalog_consumer_events WHERE kind = 'public_telegram_cta' "
                "AND start_param IN (:a, :c) ORDER BY id"
            ),
            {"a": f"arena_{arena_id}", "c": f"catalog_{city_id}"},
        )
    ).all()
    assert tuple(rows[0]) == (city_id, arena_id, True, "preview")
    assert tuple(rows[1]) == (city_id, None, False, "human")
