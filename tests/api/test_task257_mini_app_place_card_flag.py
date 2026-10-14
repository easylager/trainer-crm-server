"""TASK-257: server /p/… in Mini App only for configured telegram ids."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.shared.catalog_mini_app_place_card import mini_app_server_place_card_enabled
from tests.api.test_webapp_client_miniapp_integration import patch_client_init_auth

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_catalog_public_url_node_unit() -> None:
    proc = subprocess.run(
        ["node", "--test", "tests/js/catalog-public-url.test.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_mini_app_server_place_card_enabled_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.shared.config import get_settings

    monkeypatch.delenv("CATALOG_MINI_APP_SERVER_PLACE_CARD_TELEGRAM_IDS", raising=False)
    get_settings.cache_clear()
    assert mini_app_server_place_card_enabled(999001) is False
    get_settings.cache_clear()


def test_mini_app_server_place_card_enabled_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.shared.config import get_settings

    monkeypatch.setenv("CATALOG_MINI_APP_SERVER_PLACE_CARD_TELEGRAM_IDS", "[1001,1002]")
    get_settings.cache_clear()
    assert mini_app_server_place_card_enabled(1001) is True
    assert mini_app_server_place_card_enabled(1003) is False
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_client_session_exposes_place_card_flag(
    app_use_test_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.shared.config import get_settings

    owner_tid = 42425701
    other_tid = 42425702
    monkeypatch.setenv("CATALOG_MINI_APP_SERVER_PLACE_CARD_TELEGRAM_IDS", f"[{owner_tid}]")
    get_settings.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_init_auth(owner_tid):
            owner = await client.get(
                "/api/webapp/client/session",
                headers={"X-Telegram-Init-Data": "mock"},
            )
        with patch_client_init_auth(other_tid):
            other = await client.get(
                "/api/webapp/client/session",
                headers={"X-Telegram-Init-Data": "mock"},
            )

    get_settings.cache_clear()
    assert owner.status_code == 200
    assert other.status_code == 200
    assert owner.json()["mini_app_server_place_card"] is True
    assert other.json()["mini_app_server_place_card"] is False
