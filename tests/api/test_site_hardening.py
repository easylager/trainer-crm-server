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
            Route("/p/{city}/{slug}", lambda r: HTMLResponse(f"arena {r.path_params['slug']}")),
            Route("/api/public/arenas/{ref}/sessions", lambda r: JSONResponse({"days": []})),
            Route("/data/{n}", lambda r: JSONResponse({"n": 1})),
        ],
        middleware=[],
    )


def _client(
    monkeypatch, mode: str, threshold: int = 5, *, json_mode: str = "log", daily: int = 1000
) -> TestClient:
    reset_scrape_guard_for_tests()
    stub = SimpleNamespace(
        scrape_guard_mode=mode, scrape_guard_json_mode=json_mode, scrape_guard_window_sec=600.0,
        scrape_guard_distinct_pages=threshold, scrape_guard_daily_arenas=daily,
        scrape_guard_allowed_hosts="glideclub.by,www.glideclub.by", webapp_base_url="https://glideclub.by",
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


# ── Суточный бюджет арен, JSON расписания, ловушка ───────────────────────

SAME_SITE = {"User-Agent": HUMAN_UA, "Sec-Fetch-Site": "same-origin"}


def _arenas(client: TestClient, ua: str, n: int) -> list[int]:
    return [client.get(f"/p/minsk/arena-{i}", headers={"User-Agent": ua}).status_code for i in range(n)]


def test_daily_arena_budget_catches_a_slow_scraper(monkeypatch):
    client = _client(monkeypatch, "block", threshold=1000, daily=4)
    statuses = _arenas(client, PYTHON, 7)
    assert statuses[:4] == [200] * 4 and set(statuses[4:]) == {429}


def test_daily_budget_counts_distinct_arenas_not_reloads(monkeypatch):
    client = _client(monkeypatch, "block", threshold=1000, daily=4)
    for _ in range(20):
        assert client.get("/p/minsk/arena-1", headers={"User-Agent": HUMAN_UA}).status_code == 200


def test_daily_budget_does_not_touch_search_bots(monkeypatch):
    client = _client(monkeypatch, "block", threshold=1000, daily=4)
    assert set(_arenas(client, GOOGLEBOT, 40)) == {200}


def test_json_from_our_pages_is_allowed_and_external_is_logged(monkeypatch, caplog):
    client = _client(monkeypatch, "log", json_mode="log")
    with caplog.at_level(logging.WARNING, logger="src.api.middleware.scrape_guard"):
        assert client.get("/api/public/arenas/2/sessions", headers=SAME_SITE).status_code == 200
        assert client.get("/api/public/arenas/3/sessions", headers={"User-Agent": PYTHON}).status_code == 200
    reasons = [r.message for r in caplog.records if "reason=external_json" in r.message]
    assert len(reasons) == 1 and "ua='python-requests" in reasons[0]


def test_json_block_mode_rejects_scripts_but_not_pages_or_search_bots(monkeypatch):
    client = _client(monkeypatch, "log", json_mode="block")
    url = "/api/public/arenas/2/sessions"
    assert client.get(url, headers={"User-Agent": PYTHON}).status_code == 403  # без заголовков браузера
    assert client.get(url, headers={"User-Agent": HUMAN_UA, "Referer": "https://evil.example/p/x"}).status_code == 403
    assert client.get(url, headers={"User-Agent": HUMAN_UA, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get(url, headers={"User-Agent": HUMAN_UA, "Referer": "https://glideclub.by/p/minsk/x"}).status_code == 200
    assert client.get(url, headers={"User-Agent": HUMAN_UA, "Origin": "https://www.glideclub.by"}).status_code == 200
    assert client.get(url, headers=SAME_SITE).status_code == 200
    assert client.get(url, headers={"User-Agent": GOOGLEBOT}).status_code == 200
    assert client.get("/p/minsk/arena-1", headers={"User-Agent": PYTHON}).status_code == 200  # HTML не затронут


def test_json_requests_count_toward_the_daily_budget(monkeypatch):
    client = _client(monkeypatch, "block", threshold=1000, json_mode="log", daily=3)
    codes = [client.get(f"/api/public/arenas/{i}/sessions", headers=SAME_SITE).status_code for i in range(6)]
    assert codes[:3] == [200] * 3 and set(codes[3:]) == {429}


def test_trap_bans_the_visitor_in_block_mode_only(monkeypatch, caplog):
    client = _client(monkeypatch, "block")
    assert client.get("/p/minsk/a", headers={"User-Agent": PYTHON}).status_code == 200
    with caplog.at_level(logging.WARNING, logger="src.api.middleware.scrape_guard"):
        assert client.get("/export/schedule.json", headers={"User-Agent": PYTHON}).status_code == 404
    assert any("reason=trap" in r.message for r in caplog.records)
    assert client.get("/p/minsk/b", headers={"User-Agent": PYTHON}).status_code == 429
    assert client.get("/p/minsk/b", headers={"User-Agent": HUMAN_UA}).status_code == 200  # другой посетитель

    client = _client(monkeypatch, "log")
    client.get("/export/schedule.json", headers={"User-Agent": PYTHON})
    assert client.get("/p/minsk/b", headers={"User-Agent": PYTHON}).status_code == 200


def test_search_bot_on_the_trap_is_not_banned(monkeypatch):
    client = _client(monkeypatch, "block")
    client.get("/export/schedule.json", headers={"User-Agent": GOOGLEBOT})
    assert client.get("/p/minsk/b", headers={"User-Agent": GOOGLEBOT}).status_code == 200


def test_robots_txt_closes_the_trap_but_not_pages():
    robots = TestClient(app).get("/robots.txt").text
    assert "Disallow: /export/" in robots and "Allow: /" in robots
    assert "Disallow: /p/" not in robots and "Disallow: /c/" not in robots


# ── ИИ-ассистенты и их поиск: читают сайт, их не блокируем ───────────────

AI_AGENTS = {
    "OAI-SearchBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot",
    "ChatGPT-User": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
    "GPTBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.1; +https://openai.com/gptbot",
    "PerplexityBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
    "Perplexity-User": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)",
    "ClaudeBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
    "Claude-User": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)",
    "DuckAssistBot": "Mozilla/5.0 (compatible; DuckAssistBot/1.2; +http://duckduckgo.com/duckassistbot.html)",
    "GoogleOther": "Mozilla/5.0 (compatible; GoogleOther)",
}


@pytest.mark.parametrize("name", sorted(AI_AGENTS))
def test_ai_assistants_are_not_humans_nor_scrapers(name):
    from src.shared.ua_class import UA_SEARCH, classify_user_agent

    assert classify_user_agent(AI_AGENTS[name]) == UA_SEARCH


def test_ai_assistants_are_never_blocked_by_the_guard(monkeypatch):
    client = _client(monkeypatch, "block", threshold=5, json_mode="block", daily=3)
    for name, ua in AI_AGENTS.items():
        assert set(_arenas(client, ua, 20)) == {200}, name
        assert client.get("/api/public/arenas/2/sessions", headers={"User-Agent": ua}).status_code == 200, name
