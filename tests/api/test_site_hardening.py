"""Защита публичного сайта: красивая 404, Permissions-Policy, детектор обхода (не трогает поисковиков)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.api.app import app
from src.api.middleware import scrape_guard
from src.api.middleware.scrape_guard import ScrapeGuardMiddleware, reset_scrape_guard_for_tests

HUMAN_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15"
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
TELEGRAM = "TelegramBot (like TwitterBot)"
PYTHON = "python-requests/2.31"


# ── 404 и заголовки ──────────────────────────────────────────────────────


def test_browser_gets_branded_404_with_real_status():
    r = TestClient(app).get("/nonexistent-page", headers={"Accept": "text/html,application/xhtml+xml"})
    assert r.status_code == 404  # не «мягкая 404»: индексации нельзя отдавать 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Такой страницы нет" in r.text and 'name="robots" content="noindex"' in r.text


def test_api_and_scripts_keep_json_404():
    client = TestClient(app)
    for path, accept in (("/nonexistent-page", "application/json"), ("/api/public/nope", "text/html"), ("/webapp/nope", "text/html")):
        r = client.get(path, headers={"Accept": accept})
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}, path


def test_permissions_policy_on_site_not_on_mini_app():
    client = TestClient(app)
    assert "camera=()" in client.get("/robots.txt").headers["permissions-policy"]
    assert "permissions-policy" not in client.get("/webapp/nope").headers


# ── Детектор обхода ──────────────────────────────────────────────────────


def _guarded_app() -> Starlette:
    return Starlette(
        routes=[
            Route("/p/{n}", lambda r: HTMLResponse(f"page {r.path_params['n']}")),
            Route("/data/{n}", lambda r: JSONResponse({"n": 1})),
        ],
        middleware=[],
    )


def _client(monkeypatch, mode: str, threshold: int = 5) -> TestClient:
    reset_scrape_guard_for_tests()
    stub = SimpleNamespace(
        scrape_guard_mode=mode, scrape_guard_window_sec=600.0, scrape_guard_distinct_pages=threshold,
    )
    monkeypatch.setattr(scrape_guard, "Settings", lambda: stub)
    return TestClient(ScrapeGuardMiddleware(_guarded_app()))


def _walk(client: TestClient, ua: str, pages: int) -> list[int]:
    return [client.get(f"/p/{i}", headers={"User-Agent": ua}).status_code for i in range(pages)]


def test_log_mode_warns_once_and_never_blocks(monkeypatch, caplog):
    client = _client(monkeypatch, "log")
    with caplog.at_level(logging.WARNING, logger="src.api.middleware.scrape_guard"):
        statuses = _walk(client, HUMAN_UA, 12)
    assert set(statuses) == {200}
    assert len([r for r in caplog.records if "scrape_suspect" in r.message]) == 1


def test_block_mode_stops_a_scraper_after_threshold(monkeypatch):
    client = _client(monkeypatch, "block", threshold=5)
    statuses = _walk(client, PYTHON, 9)
    assert statuses[:5] == [200] * 5 and set(statuses[5:]) == {429}
    r = client.get("/p/99", headers={"User-Agent": PYTHON})
    assert r.status_code == 429 and r.headers["retry-after"] == "600"


@pytest.mark.parametrize("ua", [GOOGLEBOT, TELEGRAM])
def test_search_and_preview_bots_are_never_touched(monkeypatch, caplog, ua):
    client = _client(monkeypatch, "block", threshold=5)
    with caplog.at_level(logging.WARNING, logger="src.api.middleware.scrape_guard"):
        assert set(_walk(client, ua, 60)) == {200}
    assert not [r for r in caplog.records if "scrape_suspect" in r.message]


def test_same_page_and_json_do_not_count(monkeypatch):
    client = _client(monkeypatch, "block", threshold=5)
    for _ in range(30):
        assert client.get("/p/1", headers={"User-Agent": HUMAN_UA}).status_code == 200
        assert client.get("/data/1", headers={"User-Agent": HUMAN_UA}).status_code == 200


def test_off_mode_and_other_visitors_are_independent(monkeypatch):
    client = _client(monkeypatch, "off", threshold=2)
    assert set(_walk(client, PYTHON, 10)) == {200}
    client = _client(monkeypatch, "block", threshold=5)
    assert set(_walk(client, PYTHON, 5)) == {200}
    # другой отпечаток UA с того же адреса — отдельный посетитель
    assert client.get("/p/0", headers={"User-Agent": HUMAN_UA}).status_code == 200
