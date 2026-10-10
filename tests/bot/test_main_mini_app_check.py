"""TASK-223 / P1-5: проверка Main Mini App через getMe. Без Telegram и БД: Bot API — локальный aiohttp-сервер."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.bot import admin_health
from src.bot import main_mini_app_check as mod
from src.bot.main_mini_app_check import (
    CheckResult,
    check_main_mini_app,
    evaluate_get_me,
    format_health_line,
    warn_if_main_mini_app_missing,
)
from src.shared.config import Settings

TOKEN = "123456:SECRET-TOKEN"
_GET_ME_BASE = {"id": 1, "is_bot": True, "first_name": "Glide", "can_join_groups": True}


@asynccontextmanager
async def fake_bot_api(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> AsyncIterator[list[str]]:
    """Поднимает локальный «api.telegram.org» и подменяет базовый адрес в модуле."""
    seen: list[str] = []

    async def wrapped(request: web.Request) -> web.StreamResponse:
        seen.append(request.path)
        return await handler(request)

    app = web.Application()
    app.router.add_get("/bot{token}/getMe", wrapped)
    server = TestServer(app)
    await server.start_server()
    monkeypatch.setattr(mod, "_BOT_API_BASE", f"http://127.0.0.1:{server.port}")
    try:
        yield seen
    finally:
        await server.close()


def _json(result: dict) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    async def handler(_: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "result": result})

    return handler


# ---------- чистый разбор ----------


def test_evaluate_enabled() -> None:
    r = evaluate_get_me({"ok": True, "result": {**_GET_ME_BASE, "has_main_web_app": True}}, expected=True)
    assert (r.ok, r.state) == (True, "enabled")


def test_evaluate_disabled_when_expected_is_not_ok() -> None:
    r = evaluate_get_me({"ok": True, "result": {**_GET_ME_BASE, "has_main_web_app": False}}, expected=True)
    assert (r.ok, r.state) == (False, "disabled")
    assert "BotFather" in r.detail


def test_evaluate_disabled_when_not_expected_is_ok() -> None:
    r = evaluate_get_me({"ok": True, "result": {**_GET_ME_BASE, "has_main_web_app": False}}, expected=False)
    assert (r.ok, r.state) == (True, "disabled")


def test_evaluate_missing_field_in_real_get_me_means_disabled() -> None:
    r = evaluate_get_me({"ok": True, "result": dict(_GET_ME_BASE)}, expected=True)
    assert (r.ok, r.state) == (False, "disabled")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"ok": False, "error_code": 401, "description": "Unauthorized"},
        {"ok": True},
        {"ok": True, "result": "x"},
        {"ok": True, "result": {"id": 1}},  # не getMe-вид: нет ни флага, ни getMe-полей
        {"ok": True, "result": {**_GET_ME_BASE, "has_main_web_app": "yes"}},
    ],
)
def test_evaluate_unknown_never_fails_check(payload: object) -> None:
    r = evaluate_get_me(payload, expected=True)
    assert (r.ok, r.state) == (True, "unknown")


# ---------- HTTP ----------


async def test_check_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    async with fake_bot_api(monkeypatch, _json({**_GET_ME_BASE, "has_main_web_app": True})) as seen:
        r = await check_main_mini_app(TOKEN, expected=True)
    assert (r.ok, r.state) == (True, "enabled")
    assert seen == [f"/bot{TOKEN}/getMe"]


async def test_check_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    async with fake_bot_api(monkeypatch, _json({**_GET_ME_BASE, "has_main_web_app": False})):
        r = await check_main_mini_app(TOKEN, expected=True)
    assert (r.ok, r.state) == (False, "disabled")


async def test_check_unauthorized_is_unknown_and_hides_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(_: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": False, "error_code": 401, "description": "Unauthorized"}, status=401)

    async with fake_bot_api(monkeypatch, handler):
        r = await check_main_mini_app(TOKEN, expected=True)
    assert (r.ok, r.state) == (True, "unknown")
    assert "Unauthorized" in r.detail and TOKEN not in r.detail


async def test_check_server_error_html_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(_: web.Request) -> web.StreamResponse:
        return web.Response(status=502, text="<html>bad gateway</html>", content_type="text/html")

    async with fake_bot_api(monkeypatch, handler):
        r = await check_main_mini_app(TOKEN, expected=True)
    assert (r.ok, r.state) == (True, "unknown")
    assert "502" in r.detail


async def test_check_timeout_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(_: web.Request) -> web.StreamResponse:
        await asyncio.sleep(2)
        return web.json_response({"ok": True, "result": {}})

    async with fake_bot_api(monkeypatch, handler):
        r = await check_main_mini_app(TOKEN, expected=True, timeout_sec=0.1)
    assert (r.ok, r.state) == (True, "unknown")
    assert TOKEN not in r.detail


async def test_check_connection_refused_is_unknown_and_hides_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_BOT_API_BASE", "http://127.0.0.1:1")
    r = await check_main_mini_app(TOKEN, expected=True, timeout_sec=1)
    assert (r.ok, r.state) == (True, "unknown")
    assert TOKEN not in r.detail


async def test_check_empty_token_does_not_call_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_BOT_API_BASE", "http://127.0.0.1:1")
    r = await check_main_mini_app("  ", expected=True)
    assert (r.ok, r.state) == (True, "unknown")


# ---------- старт бота и /version ----------


async def test_startup_warns_and_reports_sentry_when_disabled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(mod, "_capture_sentry_message", sent.append)
    async with fake_bot_api(monkeypatch, _json({**_GET_ME_BASE, "has_main_web_app": False})):
        with caplog.at_level(logging.WARNING, logger=mod.logger.name):
            r = await warn_if_main_mini_app_missing(TOKEN, expected=True)
    assert r.state == "disabled"
    assert any(rec.levelno == logging.WARNING and "Main Mini App" in rec.getMessage() for rec in caplog.records)
    assert len(sent) == 1 and TOKEN not in sent[0]


async def test_startup_is_quiet_when_enabled_or_unknown(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(mod, "_capture_sentry_message", sent.append)
    async with fake_bot_api(monkeypatch, _json({**_GET_ME_BASE, "has_main_web_app": True})):
        with caplog.at_level(logging.WARNING, logger=mod.logger.name):
            await warn_if_main_mini_app_missing(TOKEN, expected=True)
    monkeypatch.setattr(mod, "_BOT_API_BASE", "http://127.0.0.1:1")
    with caplog.at_level(logging.WARNING, logger=mod.logger.name):
        await warn_if_main_mini_app_missing(TOKEN, expected=True)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert sent == []


def test_health_line_variants() -> None:
    assert format_health_line(CheckResult(True, "enabled", "x")) == "• Main Mini App: ok"
    assert format_health_line(CheckResult(True, "disabled", "x")) == "• Main Mini App: ok"  # не ждали — не тревога
    assert format_health_line(CheckResult(False, "disabled", "нет")).startswith("• Main Mini App: warn")
    assert format_health_line(CheckResult(True, "unknown", "таймаут")).startswith("• Main Mini App: unknown")
    assert format_health_line(None).startswith("• Main Mini App: unknown")


def test_admin_version_message_has_main_mini_app_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_health, "_last_main_mini_app", None)
    s = Settings()
    base = {"status": "ok", "db": "ok", "s3": "skip"}
    assert "Main Mini App: unknown" in admin_health.format_admin_version_message(s, base)
    warn = admin_health.format_admin_version_message(s, base, CheckResult(False, "disabled", "нет"))
    assert "Main Mini App: warn" in warn
    ok = admin_health.format_admin_version_message(s, "таймаут", CheckResult(True, "enabled", "x"))
    assert "Main Mini App: ok" in ok


async def test_fetch_api_health_refreshes_main_mini_app(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_body() -> dict:
        return {"status": "ok"}

    monkeypatch.setattr(admin_health, "_fetch_api_health_body", fake_body)
    async with fake_bot_api(monkeypatch, _json({**_GET_ME_BASE, "has_main_web_app": False})):
        health = await admin_health.fetch_api_health()
    assert health == {"status": "ok"}
    assert admin_health._last_main_mini_app is not None
    assert admin_health._last_main_mini_app.state == "disabled"
    assert "Main Mini App: warn" in admin_health.format_admin_version_message(Settings(), health)
