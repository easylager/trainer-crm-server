"""Ice map incident 2026-10-07: map-config skip, photo bucket, HTML meta key, non-blocking photos."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.api.middleware.http_limits import reset_http_limiters_for_tests


@pytest.fixture(autouse=True)
def _reset_limiters():
    reset_http_limiters_for_tests()
    yield
    reset_http_limiters_for_tests()


@pytest.mark.asyncio
async def test_map_config_and_photos_survive_public_bucket_exhaustion(monkeypatch, app_use_test_db) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_PUBLIC_MAX_REQUESTS", "1")
    monkeypatch.setenv("API_RATE_LIMIT_PUBLIC_WINDOW_SEC", "60")
    monkeypatch.setenv("API_RATE_LIMIT_PHOTO_MAX_REQUESTS", "100")
    reset_http_limiters_for_tests()

    def mock_get_photo(_key: str):
        return None

    with patch("src.api.routes.public.s3.get_photo", mock_get_photo):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/public/cities")).status_code == 200
            assert (await client.get("/api/public/cities")).status_code == 429
            map_cfg = await client.get("/api/public/ice/map-config")
            assert map_cfg.status_code == 200
            photo = await client.get("/api/public/photos/trainers/missing-file.jpg")
            assert photo.status_code == 404
            assert photo.status_code != 429


@pytest.mark.asyncio
async def test_webapp_ice_html_injects_ymaps_meta_when_key_set(monkeypatch, app_use_test_db) -> None:
    monkeypatch.setenv("YANDEX_MAPS_JS_API_KEY", "html-injected-key")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/webapp/ice")
    assert resp.status_code == 200
    assert 'name="ymaps-key"' in resp.text
    assert 'content="html-injected-key"' in resp.text
    assert resp.headers.get("cache-control", "").lower().find("no-store") >= 0


@pytest.mark.asyncio
async def test_webapp_ice_html_omits_ymaps_meta_without_key(monkeypatch, app_use_test_db) -> None:
    monkeypatch.setenv("YANDEX_MAPS_JS_API_KEY", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/webapp/ice")
    assert resp.status_code == 200
    assert 'name="ymaps-key"' not in resp.text


@pytest.mark.asyncio
async def test_serve_photo_does_not_block_event_loop(app_use_test_db) -> None:
    slow = asyncio.Event()

    def slow_get_photo(_key: str):
        time.sleep(0.35)
        return (b"ok", "image/jpeg")

    with patch("src.api.routes.public.s3.get_photo", slow_get_photo):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            slow_task = asyncio.create_task(client.get("/api/public/photos/trainers/slow.jpg"))
            await asyncio.sleep(0.05)
            t_fast = time.monotonic()
            fast = await client.get("/health")
            fast_elapsed = time.monotonic() - t_fast
            slow_resp = await slow_task
    assert fast.status_code == 200
    assert slow_resp.status_code == 200
    assert fast_elapsed < 0.15, "fast request must not wait for slow S3 mock on another route"
    assert "immutable" in (slow_resp.headers.get("cache-control") or "")
    assert (slow_resp.headers.get("content-type") or "").startswith("image/jpeg")


@pytest.mark.asyncio
async def test_ymaps_meta_escapes_special_characters(monkeypatch, app_use_test_db) -> None:
    monkeypatch.setenv("YANDEX_MAPS_JS_API_KEY", 'a"<>&b')
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/webapp/ice")
    assert 'content="a&quot;&lt;&gt;&amp;b"' in resp.text


@pytest.mark.asyncio
async def test_rate_limit_warning_masks_ip_and_does_not_flood(monkeypatch, app_use_test_db, caplog) -> None:
    import logging

    monkeypatch.setenv("API_RATE_LIMIT_PUBLIC_MAX_REQUESTS", "1")
    monkeypatch.setenv("API_RATE_LIMIT_PUBLIC_WINDOW_SEC", "60")
    reset_http_limiters_for_tests()
    with caplog.at_level(logging.WARNING):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/public/cities")).status_code == 200
            assert (await client.get("/api/public/cities")).status_code == 429
            assert (await client.get("/api/public/cities")).status_code == 429
    hits = [r.getMessage() for r in caplog.records if "rate limit exceeded" in r.getMessage()]
    assert len(hits) == 1
    assert "ip=127.0.0.0/16" in hits[0]
    assert "127.0.0.1" not in hits[0]


def test_mask_client_ip_uses_prefix_for_short_ipv6() -> None:
    import src.api.middleware.http_limits as http_limits
    from src.api.middleware.http_limits import _mask_client_ip, _prune_rate_limit_warns

    assert _mask_client_ip("127.0.0.1") == "127.0.0.0/16"
    assert _mask_client_ip("2a02::1") == "2a02::/48"
    assert _mask_client_ip("fe80::1") == "fe80::/48"
    assert _mask_client_ip("2a02::1") != "2a02::1"
    assert _mask_client_ip("::ffff:1.2.3.4") == "1.2.0.0/16"
    assert _mask_client_ip("::ffff:192.168.1.1") == "192.168.0.0/16"
    http_limits._rate_limit_warn_at.clear()
    http_limits._rate_limit_warn_at[("public", "stale")] = 0.0
    _prune_rate_limit_warns(601.0)
    assert ("public", "stale") not in http_limits._rate_limit_warn_at


@pytest.mark.asyncio
async def test_map_config_warns_when_key_empty(monkeypatch, app_use_test_db, caplog) -> None:
    import logging

    import src.api.routes.public_arenas as public_arenas

    public_arenas._map_config_empty_warned_at = float("-inf")
    monkeypatch.setenv("YANDEX_MAPS_JS_API_KEY", "")
    with caplog.at_level(logging.WARNING):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get("/api/public/ice/map-config")
            second = await client.get("/api/public/ice/map-config")
    assert first.status_code == 200
    assert second.headers["cache-control"] == "no-store"
    hits = [r for r in caplog.records if "YANDEX_MAPS_JS_API_KEY is empty" in r.getMessage()]
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_map_config_warns_first_empty_immediately(monkeypatch, app_use_test_db, caplog) -> None:
    import logging
    import time

    import src.api.routes.public_arenas as public_arenas

    public_arenas._map_config_empty_warned_at = time.monotonic() - 300.0
    monkeypatch.setenv("YANDEX_MAPS_JS_API_KEY", "")
    with caplog.at_level(logging.WARNING):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/api/public/ice/map-config")
    hits = [r for r in caplog.records if "YANDEX_MAPS_JS_API_KEY is empty" in r.getMessage()]
    assert len(hits) == 1
