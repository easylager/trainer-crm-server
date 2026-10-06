"""Epic D: API rate limit (IP) and body-size helpers."""
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from src.api.app import app
from src.api.middleware.http_limits import (
    client_ip_from_request,
    max_body_bytes_for_path,
    rate_limit_bucket_for_path,
    reset_http_limiters_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_rate_limiters_between_tests():
    reset_http_limiters_for_tests()
    yield
    reset_http_limiters_for_tests()


def test_rate_limit_bucket_for_path():
    assert rate_limit_bucket_for_path("/health") == "skip"
    assert rate_limit_bucket_for_path("/webapp/x") == "skip"
    assert rate_limit_bucket_for_path("/go") == "public"
    assert rate_limit_bucket_for_path("/go/insta") == "public"
    assert rate_limit_bucket_for_path("/go/flyer-olimpik/minsk") == "public"
    assert rate_limit_bucket_for_path("/gopher") == "skip"
    assert rate_limit_bucket_for_path("/api/webhooks/bepaid") == "skip"
    assert rate_limit_bucket_for_path("/api/public/cities") == "public"
    assert rate_limit_bucket_for_path("/api/webapp/schedule") == "webapp"
    assert rate_limit_bucket_for_path("/api/upload/photo") == "upload"
    assert rate_limit_bucket_for_path("/api/trainers") == "default"
    # TASK-190: публичные страницы и PNG больше не "skip"
    assert rate_limit_bucket_for_path("/p/minsk/olimp") == "page"
    assert rate_limit_bucket_for_path("/c/minsk") == "page"
    assert rate_limit_bucket_for_path("/ice/minsk/today") == "page"
    assert rate_limit_bucket_for_path("/r/tg/5") == "page"
    assert rate_limit_bucket_for_path("/p/minsk/olimp/og.png") == "image"
    assert rate_limit_bucket_for_path("/p/minsk/olimp/session/3/story.png") == "image"
    assert rate_limit_bucket_for_path("/c/minsk/og.png") == "image"
    assert rate_limit_bucket_for_path("/ice/minsk/today/og.png") == "image"
    assert rate_limit_bucket_for_path("/cabinet") == "skip"


def test_client_ip_from_x_forwarded_for_is_rightmost_trusted_hop():
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"10.0.0.1, 203.0.113.1")],
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
        "server": ("test", 80),
    }
    req = Request(scope)
    assert client_ip_from_request(req) == "203.0.113.1"


def test_max_body_bytes_for_path():
    assert max_body_bytes_for_path("/api/webhooks/bepaid") >= max_body_bytes_for_path("/api/public/cities")
    assert max_body_bytes_for_path("/api/upload/photo") >= max_body_bytes_for_path("/api/trainers")
    assert max_body_bytes_for_path("/api/webapp/trainer/photos") >= max_body_bytes_for_path("/api/webapp/client/session")
    assert max_body_bytes_for_path("/api/webapp/admin/arenas/9/photos") >= max_body_bytes_for_path(
        "/api/webapp/admin/arenas/9"
    )


@pytest.mark.asyncio
async def test_public_api_rate_limit_returns_429(monkeypatch, app_use_test_db) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_PUBLIC_MAX_REQUESTS", "1")
    monkeypatch.setenv("API_RATE_LIMIT_PUBLIC_WINDOW_SEC", "60")
    reset_http_limiters_for_tests()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get("/api/public/cities")
        r2 = await client.get("/api/public/cities")
    assert r1.status_code == 200
    assert r2.status_code == 429
    assert r2.json().get("detail") == "Too many requests"


@pytest.mark.asyncio
async def test_rate_limit_disabled_skips_429(monkeypatch, app_use_test_db) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("API_RATE_LIMIT_PUBLIC_MAX_REQUESTS", "1")
    reset_http_limiters_for_tests()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get("/api/public/cities")
        r2 = await client.get("/api/public/cities")
    assert r1.status_code == 200
    assert r2.status_code == 200
