"""TASK-177: catalog prod hygiene — visibility scope, publish guard, merged redirects, TTL."""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.admin_arena_moderation import approve_arena
from src.application.arena_profile import (
    PUBLISH_BLOCKER_NO_COORDINATES,
    PUBLISH_BLOCKER_TEST_NAME,
    ArenaNotPublishableError,
    apply_admin_arena_profile_patch,
    arena_publish_blockers,
    ensure_arena_profile,
    looks_like_test_arena_name,
)
from src.application.arena_public_use_cases import find_nearest_ice_now, get_hub_ice_teaser
from src.application.ice_city_day import city_slug
from src.infrastructure.repositories.catalog_repository import CatalogRepository
from src.ingestion.ttl import expire_past_ice_sessions, purge_ice_scrape_ttl
from tests.api.test_public_arenas import (
    _add_future_session,
    _insert_arena,
    _insert_bare_trainer,
    _insert_city,
)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _slug(db_session, arena_id: int) -> str:
    return (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
    ).scalar_one()


async def _profile_status(db_session, arena_id: int) -> str:
    return (
        await db_session.execute(
            text("SELECT status FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id}
        )
    ).scalar_one()


async def _assert_hidden_everywhere(db_session, *, city_id: int, city_name: str, arena_id: int) -> None:
    """Every public surface: list (city + bbox), search, card, sessions, sitemap, /p/, /c/,
    /ice/{city}/today, city share, nearest, hub teaser."""
    slug = await _slug(db_session, arena_id)
    cslug = city_slug(city_name)
    async with _client() as client:
        by_city = await client.get("/api/public/ice/arenas", params={"city_id": city_id, "intent": "coach"})
        bbox = await client.get(
            "/api/public/ice/arenas", params={"bbox": "54.40,28.40,54.42,28.42", "intent": "coach", "limit": 100}
        )
        search = await client.get("/api/public/search", params={"q": "Скрытник"})
        card = await client.get(f"/api/public/arenas/{arena_id}")
        sessions = await client.get(f"/api/public/arenas/{arena_id}/sessions")
        sitemap = await client.get("/sitemap.xml")
        place = await client.get(f"/p/{cslug}/{slug}")
        place_by_id = await client.get(f"/p/{arena_id}", follow_redirects=False)
        selection = await client.get(f"/c/{cslug}")
        today = await client.get(f"/ice/{cslug}/today")
        share = await client.get(f"/api/public/ice/share/{city_id}")
        cities = await client.get("/api/public/ice/cities")
    assert by_city.status_code == 200 and arena_id not in {i["id"] for i in by_city.json()["items"]}
    assert bbox.status_code == 200 and arena_id not in {i["id"] for i in bbox.json()["items"]}
    assert search.status_code == 200
    arena_hits = next(g for g in search.json()["groups"] if g["type"] == "arena")["items"]
    city_hits = next(g for g in search.json()["groups"] if g["type"] == "city")["items"]
    assert arena_id not in {i["id"] for i in arena_hits}
    assert city_id not in {i["id"] for i in city_hits}
    assert card.status_code == 404
    assert sessions.status_code == 404
    assert f"/{slug}<" not in sitemap.text and f"/c/{cslug}<" not in sitemap.text
    assert place.status_code == 404
    assert place_by_id.status_code == 404
    assert selection.status_code == 404
    assert today.status_code == 404
    assert share.status_code == 404
    assert city_id not in {int(i["id"]) for i in cities.json()["items"]}
    near = await find_nearest_ice_now(db_session, near="53.90,27.56")
    assert near is None or near["arena_id"] != arena_id
    teaser = await get_hub_ice_teaser(db_session, city_id=city_id)
    assert teaser is None


async def _visible_arena(db_session, *, country: str = "BY") -> tuple[int, str, int]:
    city_name = f"Скрытово {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=city_name, country=country)
    arena_id = await _insert_arena(
        db_session, city_id, name=f"Скрытник {uuid.uuid4().hex[:4]}", latitude=54.41, longitude=28.41
    )
    await _add_future_session(db_session, arena_id, days_ahead=0, starts_at_local="23:30")
    await _add_future_session(db_session, arena_id, days_ahead=1)
    await db_session.commit()
    return city_id, city_name, arena_id


@pytest.mark.asyncio
async def test_visible_arena_baseline_is_public(app_use_test_db, db_session) -> None:
    """Control for the hidden-everywhere checks: the same setup in an active BY city shows."""
    city_id, city_name, arena_id = await _visible_arena(db_session)
    async with _client() as client:
        by_city = await client.get("/api/public/ice/arenas", params={"city_id": city_id, "intent": "coach"})
        bbox = await client.get(
            "/api/public/ice/arenas", params={"bbox": "54.40,28.40,54.42,28.42", "intent": "coach", "limit": 100}
        )
        card = await client.get(f"/api/public/arenas/{arena_id}")
        sitemap = await client.get("/sitemap.xml")
        today = await client.get(f"/ice/{city_slug(city_name)}/today")
        selection = await client.get(f"/c/{city_slug(city_name)}")
    assert arena_id in {i["id"] for i in by_city.json()["items"]}
    assert arena_id in {i["id"] for i in bbox.json()["items"]}
    assert (await get_hub_ice_teaser(db_session, city_id=city_id)) is not None
    assert card.status_code == 200
    assert f"/c/{city_slug(city_name)}<" in sitemap.text
    assert today.status_code == 200
    assert selection.status_code == 200


@pytest.mark.asyncio
async def test_deactivated_city_disappears_from_every_public_surface(app_use_test_db, db_session) -> None:
    """AC-4: cities.is_active=false hides the city and its arenas everywhere."""
    city_id, city_name, arena_id = await _visible_arena(db_session)
    await db_session.execute(text("UPDATE cities SET is_active = false WHERE id = :id"), {"id": city_id})
    await db_session.commit()
    await _assert_hidden_everywhere(db_session, city_id=city_id, city_name=city_name, arena_id=arena_id)


@pytest.mark.asyncio
async def test_ru_city_hidden_everywhere_under_by_scope(app_use_test_db, db_session, monkeypatch) -> None:
    """AC-3 (code side): with ICE_DISCOVERY_COUNTRIES=BY an active RU city is not public."""
    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY")
    city_id, city_name, arena_id = await _visible_arena(db_session, country="RU")
    await _assert_hidden_everywhere(db_session, city_id=city_id, city_name=city_name, arena_id=arena_id)


@pytest.mark.asyncio
async def test_platform_stats_counts_only_published_ice_in_visible_countries(app_use_test_db, db_session) -> None:
    """AC-6: arenas_count = published ice arenas of the discovery countries."""
    repo = CatalogRepository(db_session)
    before = (await repo.platform_stats())["arenas_count"]
    by_city = await _insert_city(db_session, name=f"Счётск {uuid.uuid4().hex[:6]}")
    ru_city = await _insert_city(db_session, name=f"Счётов {uuid.uuid4().hex[:6]}", country="RU")
    off_city = await _insert_city(db_session, name=f"Выкл {uuid.uuid4().hex[:6]}")
    await db_session.execute(text("UPDATE cities SET is_active = false WHERE id = :id"), {"id": off_city})
    await _insert_arena(db_session, by_city, name="Лёд для счёта")
    shop = await _insert_arena(db_session, by_city, name="Магазин коньков")
    await db_session.execute(text("UPDATE arenas SET venue_type = 'shop' WHERE id = :id"), {"id": shop})
    archived = await _insert_arena(db_session, by_city, name="Архивный лёд")
    await db_session.execute(
        text("UPDATE arena_profiles SET status = 'archived' WHERE arena_id = :id"), {"id": archived}
    )
    await _insert_arena(db_session, ru_city, name="Московский лёд")
    await _insert_arena(db_session, off_city, name="Лёд в выключенном городе")
    await db_session.flush()
    after = (await repo.platform_stats())["arenas_count"]
    assert after - before == 1


# --- publish guard -----------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Тестовая Арена 1", True),
        ("тест", True),
        ("Test rink", True),
        ("Arena-test", True),
        ("Протестантский каток", False),
        ("Contest Arena", False),
        ("ТЦ Замок", False),
        ("", False),
    ],
)
def test_looks_like_test_arena_name(name: str, expected: bool) -> None:
    assert looks_like_test_arena_name(name) is expected


def test_publish_blockers_require_coords_for_ice_only() -> None:
    assert arena_publish_blockers(name="Каток", venue_type="ice", latitude=None, longitude=27.5) == [
        PUBLISH_BLOCKER_NO_COORDINATES
    ]
    assert arena_publish_blockers(name="Магазин", venue_type="shop", latitude=None, longitude=None) == []
    assert arena_publish_blockers(name="Тестовая", venue_type="ice", latitude=53.0, longitude=27.0) == [
        PUBLISH_BLOCKER_TEST_NAME
    ]
    assert arena_publish_blockers(name="ТЦ Замок", venue_type="ice", latitude=53.0, longitude=27.0) == []


async def _raw_arena(db_session, city_id: int, *, name: str, lat=53.9, lon=27.5, confirmed=True, by=None) -> int:
    return int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO arenas (city_id, name, latitude, longitude, is_active, is_confirmed, "
                    "created_by_trainer_id) VALUES (:c, :n, :lat, :lon, true, :conf, :by) RETURNING id"
                ),
                {"c": city_id, "n": name, "lat": lat, "lon": lon, "conf": confirmed, "by": by},
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_test_named_arena_is_created_as_draft_and_cannot_be_published(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Гардск {uuid.uuid4().hex[:6]}")
    arena_id = await _raw_arena(db_session, city_id, name="Тестовая Арена 9")
    await ensure_arena_profile(db_session, arena_id, city_id=city_id, name="Тестовая Арена 9")
    assert await _profile_status(db_session, arena_id) == "draft"
    with pytest.raises(ArenaNotPublishableError):
        await apply_admin_arena_profile_patch(db_session, arena_id, {"status": "published"})
    assert await _profile_status(db_session, arena_id) == "draft"


@pytest.mark.asyncio
async def test_coordless_rink_cannot_be_switched_to_published(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Гардск {uuid.uuid4().hex[:6]}")
    arena_id = await _raw_arena(db_session, city_id, name="Каток без точки", lat=None, lon=None)
    await ensure_arena_profile(db_session, arena_id, city_id=city_id, name="Каток без точки", status="draft")
    with pytest.raises(ArenaNotPublishableError):
        await apply_admin_arena_profile_patch(db_session, arena_id, {"status": "published"})
    # Re-saving an already published legacy row is not a transition and keeps working.
    legit = await _raw_arena(db_session, city_id, name="Обычный каток", lat=None, lon=None)
    await ensure_arena_profile(db_session, legit, city_id=city_id, name="Обычный каток")
    await apply_admin_arena_profile_patch(db_session, legit, {"status": "published", "phone": "+375"})
    assert await _profile_status(db_session, legit) == "published"


@pytest.mark.asyncio
async def test_admin_api_refuses_publishing_test_arena(app_use_test_db, db_session, monkeypatch) -> None:
    """Admin PATCH surfaces the guard as 400, not a silent publish."""
    from src.api.miniapp_auth.deps import get_admin_miniapp_principal

    city_id = await _insert_city(db_session, name=f"Гардск {uuid.uuid4().hex[:6]}")
    arena_id = await _raw_arena(db_session, city_id, name="Test arena")
    await ensure_arena_profile(db_session, arena_id, city_id=city_id, name="Test arena")
    await db_session.commit()
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: object()
    try:
        async with _client() as client:
            resp = await client.patch(f"/api/webapp/admin/arenas/{arena_id}", json={"status": "published"})
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)
    assert resp.status_code == 400, resp.text
    assert "test_name" in resp.text


@pytest.mark.asyncio
async def test_approve_refuses_test_arena_and_publishes_parked_draft(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Модерск {uuid.uuid4().hex[:6]}")
    trainer_id = await _insert_bare_trainer(db_session)
    test_arena = await _raw_arena(db_session, city_id, name="Тестовая Арена 3", confirmed=False, by=trainer_id)
    await ensure_arena_profile(db_session, test_arena, city_id=city_id, name="Тестовая Арена 3")
    assert await approve_arena(db_session, test_arena, admin_id=1) is False
    confirmed = (
        await db_session.execute(text("SELECT is_confirmed FROM arenas WHERE id = :id"), {"id": test_arena})
    ).scalar_one()
    assert confirmed is False

    real = await _raw_arena(db_session, city_id, name="Новый каток", confirmed=False, by=trainer_id)
    await ensure_arena_profile(db_session, real, city_id=city_id, name="Новый каток", status="draft")
    assert await approve_arena(db_session, real, admin_id=1) is True
    assert await _profile_status(db_session, real) == "published"


# --- merged duplicates: 301 ----------------------------------------------------


@pytest.mark.asyncio
async def test_retired_duplicate_place_urls_redirect_301_to_canonical(app_use_test_db, db_session) -> None:
    """AC-2: the duplicate's /p/{id} and /p/{city}/{slug} answer 301 to the canonical page."""
    canon_city_name = f"Канонск {uuid.uuid4().hex[:6]}"
    dup_city_name = f"Дублинск {uuid.uuid4().hex[:6]}"
    canon_city = await _insert_city(db_session, name=canon_city_name)
    dup_city = await _insert_city(db_session, name=dup_city_name)
    canon = await _insert_arena(db_session, canon_city, name="Ледовый дворец")
    dup = await _insert_arena(db_session, dup_city, name="Ледовый дворец копия")
    dup_slug = await _slug(db_session, dup)
    canon_path = f"/p/{city_slug(canon_city_name)}/{await _slug(db_session, canon)}"
    await db_session.execute(
        text("UPDATE arenas SET merged_into_arena_id = :c, is_active = false WHERE id = :d"),
        {"c": canon, "d": dup},
    )
    await db_session.execute(text("UPDATE arena_profiles SET status = 'archived' WHERE arena_id = :d"), {"d": dup})
    await db_session.commit()
    async with _client() as client:
        by_id = await client.get(f"/p/{dup}?s=5", follow_redirects=False)
        by_slug = await client.get(f"/p/{city_slug(dup_city_name)}/{dup_slug}", follow_redirects=False)
        plain_missing = await client.get("/p/999999999", follow_redirects=False)
    assert by_id.status_code == 301
    assert by_id.headers["location"] == canon_path + "?s=5"
    assert by_slug.status_code == 301
    assert by_slug.headers["location"] == canon_path
    assert plain_missing.status_code == 404


# --- TTL -------------------------------------------------------------------------


async def _raw_session(db_session, arena_id: int, *, ends_ago: timedelta, status: str = "active") -> int:
    now = datetime.now(timezone.utc)
    ends = now - ends_ago
    starts = ends - timedelta(minutes=60)
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_sessions (arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                        starts_at_local, ends_at_local, currency_code, status)
                    VALUES (:a, 'public_skate', :s, :e, :d, :sl, :el, 'BYN', :st)
                    RETURNING id
                    """
                ),
                {
                    "a": arena_id,
                    "s": starts,
                    "e": ends,
                    "d": starts.date(),
                    "sl": time(starts.hour, starts.minute),
                    "el": time(ends.hour, ends.minute),
                    "st": status,
                },
            )
        ).scalar_one()
    )


async def _status(db_session, session_id: int) -> str | None:
    return (
        await db_session.execute(text("SELECT status FROM ice_sessions WHERE id = :id"), {"id": session_id})
    ).scalar()


@pytest.mark.asyncio
async def test_ttl_expires_past_active_sessions_and_keeps_recent_history(app_use_test_db, db_session) -> None:
    """AC-5: active sessions ended > 1 day ago become expired; < 1 day stays; > 14 days deleted."""
    city_id = await _insert_city(db_session, name=f"Ттлск {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Каток TTL")
    old = await _raw_session(db_session, arena_id, ends_ago=timedelta(days=3))
    cancelled = await _raw_session(db_session, arena_id, ends_ago=timedelta(days=3), status="cancelled")
    recent = await _raw_session(db_session, arena_id, ends_ago=timedelta(hours=5))
    ancient = await _raw_session(db_session, arena_id, ends_ago=timedelta(days=20))
    future = await _add_future_session(db_session, arena_id, days_ahead=2)
    stats = await purge_ice_scrape_ttl(db_session, now=datetime.now(timezone.utc))
    assert stats.sessions_expired >= 1
    assert await _status(db_session, old) == "expired"
    assert await _status(db_session, cancelled) == "cancelled"
    assert await _status(db_session, recent) == "active"
    assert await _status(db_session, ancient) is None
    assert await _status(db_session, future) == "active"
    left = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM ice_sessions WHERE status = 'active' "
                "AND ends_at_utc < now() - interval '1 day'"
            )
        )
    ).scalar_one()
    assert left == 0
    assert await expire_past_ice_sessions(db_session, now=datetime.now(timezone.utc)) == 0


