"""Admin «Источники расписаний»: mode derivation, health status, list query and save."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.application.admin_ice_sources import (
    SourceValidationError,
    detect_source_kind,
    effective_fetch_mode,
    health_status,
    list_admin_ice_sources,
    normalize_source_url,
    save_admin_ice_source,
)


def test_detect_source_kind():
    assert detect_source_kind("https://www.instagram.com/rink") == "instagram"
    assert detect_source_kind("https://vk.com/zor.zhlobin") == "vk"
    assert detect_source_kind("https://m.vk.com/x") == "vk"
    assert detect_source_kind("https://t.me/zorzhlobin") == "telegram"
    assert detect_source_kind("https://24afisha.by/ru/object/5159") == "afisha"
    assert detect_source_kind("https://rink.by/schedule") == "site"
    assert detect_source_kind(None) is None
    # a lookalike host must not count as Instagram
    assert detect_source_kind("https://notinstagram.com/x") == "site"


def test_normalize_source_url():
    assert normalize_source_url("  instagram.com/rink ") == "https://instagram.com/rink"
    assert normalize_source_url("") is None
    with pytest.raises(SourceValidationError):
        normalize_source_url("javascript:alert(1)")
    with pytest.raises(SourceValidationError):
        normalize_source_url("не ссылка")


def test_effective_mode_derivation():
    assert effective_fetch_mode("manual", None, False) == ("manual", True)
    assert effective_fetch_mode(None, None, False) == ("none", False)
    assert effective_fetch_mode(None, "manual_schedule_v1", False) == ("manual", False)
    assert effective_fetch_mode(None, "gorki_lds_v1", True) == ("byip", False)
    assert effective_fetch_mode(None, "zamok_html_v1", False) == ("server", False)


def test_health_status():
    assert health_status("none", 0, None, 0) == "none"
    assert health_status("manual", 14, "empty_after_slots", 18) == "ok"
    assert health_status("manual", 0, None, 0) == "waiting"
    assert health_status("server", 51, "timeout", 4) == "broken"
    assert health_status("server", 2, "empty_source", 0) == "empty"
    assert health_status("server", 0, None, 0) == "empty"
    assert health_status("server", 0, None, 5) == "ok"
    # empty-after-filter streaks are an empty source, not a broken one


@pytest.mark.asyncio
async def test_list_and_save_roundtrip(db_session):
    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9901, 'ТестГород', 'BY', true)"))
    await db_session.execute(
        text(
            "INSERT INTO arenas (id, name, city_id, is_active, is_confirmed, venue_type) "
            "VALUES (9902, 'Тест-арена', 9901, true, true, 'ice')"
        )
    )
    await db_session.execute(
        text("INSERT INTO arena_profiles (arena_id, city_id, slug, status) VALUES (9902, 9901, 'test-arena', 'published')")
    )
    await db_session.commit()

    data = await list_admin_ice_sources(db_session)
    item = next(i for i in data["items"] if i["arena_id"] == 9902)
    assert item["mode"] == "none" and item["status"] == "none" and item["source_url"] is None

    assert await save_admin_ice_source(
        db_session, arena_id=9902, source_url="instagram.com/test_rink", fetch_mode="manual",
        publish_days=[1, 0, 1], remind=True, admin_telegram_id=7,
    )
    data = await list_admin_ice_sources(db_session)
    item = next(i for i in data["items"] if i["arena_id"] == 9902)
    assert item["mode"] == "manual" and item["mode_set_by_admin"] is True
    assert item["source_kind"] == "instagram" and item["source_url"] == "https://instagram.com/test_rink"
    assert item["publish_days"] == [0, 1] and item["remind"] is True

    with pytest.raises(SourceValidationError):
        await save_admin_ice_source(
            db_session, arena_id=9902, source_url=None, fetch_mode="bogus", publish_days=[], remind=False,
            admin_telegram_id=7,
        )
    with pytest.raises(SourceValidationError):
        await save_admin_ice_source(
            db_session, arena_id=9902, source_url=None, fetch_mode="none", publish_days=[7], remind=False,
            admin_telegram_id=7,
        )
    assert not await save_admin_ice_source(
        db_session, arena_id=999999, source_url=None, fetch_mode="none", publish_days=[], remind=False,
        admin_telegram_id=7,
    )


@pytest.mark.asyncio
async def test_api_endpoints(db_session):
    from httpx import ASGITransport, AsyncClient

    from src.api.app import app
    from src.api.miniapp_auth.deps import get_admin_miniapp_principal
    from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal

    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9911, 'ТестГород2', 'BY', true)"))
    await db_session.execute(
        text(
            "INSERT INTO arenas (id, name, city_id, is_active, is_confirmed, venue_type) "
            "VALUES (9912, 'Тест-арена 2', 9911, true, true, 'ice')"
        )
    )
    await db_session.execute(
        text("INSERT INTO arena_profiles (arena_id, city_id, slug, status) VALUES (9912, 9911, 'test-arena-2', 'published')")
    )
    await db_session.commit()
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: MiniAppPrincipal(
        platform=MiniAppPlatform.TELEGRAM, user_id=4242
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/webapp/admin/ice-sources")
            assert r.status_code == 200 and any(i["arena_id"] == 9912 for i in r.json()["items"])
            ok = await c.put(
                "/api/webapp/admin/ice-sources/9912",
                json={"source_url": "vk.com/rink", "fetch_mode": "manual", "publish_days": [0], "remind": False},
            )
            assert ok.status_code == 200
            bad = await c.put("/api/webapp/admin/ice-sources/9912", json={"source_url": "x y", "fetch_mode": "manual"})
            assert bad.status_code == 400
            missing = await c.put("/api/webapp/admin/ice-sources/999999", json={"fetch_mode": "none"})
            assert missing.status_code == 404
            assert (await c.get("/webapp/admin-ice-sources")).status_code == 200
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)
