"""Публичные ручки: креденшл клиента необязателен и никогда не даёт 401/503."""

from __future__ import annotations

import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.api.miniapp_auth.deps import get_optional_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from tests.shared.test_telegram_webapp import _build_signed_init_data

_TOKEN = "123456:ABC-DEF"


class _ClientSecrets:
    def __init__(self, token: str = _TOKEN, vk: str = "") -> None:
        self.telegram_bot_token_client = token
        self.vk_mini_app_protected_key = vk


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    def who(
        principal: MiniAppPrincipal | None = Depends(get_optional_client_miniapp_principal),
    ) -> dict:
        if principal is None:
            return {"user_id": None, "platform": None}
        return {"user_id": principal.user_id, "platform": principal.platform.value}

    return app


def _who(headers: dict[str, str] | None = None, params: dict[str, str] | None = None) -> tuple[int, dict]:
    response = TestClient(_app()).get("/who", headers=headers or {}, params=params or {})
    return response.status_code, response.json()


def test_optional_principal_is_none_without_credential() -> None:
    status, body = _who()
    assert status == 200
    assert body == {"user_id": None, "platform": None}


def test_optional_principal_is_none_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientSecrets())
    status, body = _who({"X-Telegram-Init-Data": "%%%not-init-data"})
    assert status == 200
    assert body["user_id"] is None


def test_optional_principal_is_none_on_unsigned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientSecrets())
    raw = "auth_date=1700000000&user=%7B%22id%22%3A42%7D&hash=" + ("ab" * 32)
    status, body = _who({"X-Telegram-Init-Data": raw})
    assert status == 200
    assert body["user_id"] is None


def test_optional_principal_is_none_when_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientSecrets())
    raw = _build_signed_init_data(_TOKEN, user_id=42, auth_date=int(time.time()) - 200_000)
    status, body = _who({"X-Telegram-Init-Data": raw})
    assert status == 200
    assert body["user_id"] is None


def test_optional_principal_is_none_when_secret_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientSecrets(token=""))
    raw = _build_signed_init_data(_TOKEN, user_id=42, auth_date=int(time.time()))
    status, body = _who({"X-Telegram-Init-Data": raw})
    assert status == 200
    assert body["user_id"] is None


def test_optional_principal_is_none_on_unsupported_platform() -> None:
    status, body = _who({"X-Mini-App-Platform": "facebook", "X-Telegram-Init-Data": "anything"})
    assert status == 200
    assert body["user_id"] is None


def test_optional_principal_from_valid_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientSecrets())
    raw = _build_signed_init_data(_TOKEN, user_id=42, auth_date=int(time.time()))
    status, body = _who({"X-Telegram-Init-Data": raw})
    assert status == 200
    assert body == {"user_id": 42, "platform": MiniAppPlatform.TELEGRAM.value}


def test_optional_principal_from_valid_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientSecrets())
    raw = _build_signed_init_data(_TOKEN, user_id=77, auth_date=int(time.time()))
    status, body = _who(params={"init_data": raw})
    assert status == 200
    assert body["user_id"] == 77
