"""ClientMenuSyncMiddleware: hub menu button must self-heal when Telegram drops it."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from src.bot.middlewares.client_menu_sync_middleware import ClientMenuSyncMiddleware


def _private_message(chat_id: int = 99) -> Message:
    msg = MagicMock(spec=Message)
    msg.chat = SimpleNamespace(id=chat_id, type="private")
    msg.bot = SimpleNamespace()
    return msg


@pytest.mark.asyncio
async def test_menu_sync_reapplies_when_not_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    sync_mock = AsyncMock()
    monkeypatch.setattr(
        "src.bot.middlewares.client_menu_sync_middleware.sync_client_hub_menu_button",
        sync_mock,
    )
    mw = ClientMenuSyncMiddleware()
    handler = AsyncMock(return_value="ok")
    msg = _private_message()

    out = await mw(handler, msg, {})
    assert out == "ok"
    sync_mock.assert_awaited_once_with(msg.bot, 99)


@pytest.mark.asyncio
async def test_menu_sync_skips_when_recently_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    sync_mock = AsyncMock()
    monkeypatch.setattr(
        "src.bot.middlewares.client_menu_sync_middleware.sync_client_hub_menu_button",
        sync_mock,
    )
    mw = ClientMenuSyncMiddleware()
    mw._last_time[99] = time.monotonic()

    handler = AsyncMock(return_value="ok")
    msg = _private_message()

    out = await mw(handler, msg, {})
    assert out == "ok"
    sync_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_menu_sync_failure_does_not_break_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.bot.middlewares.client_menu_sync_middleware.sync_client_hub_menu_button",
        AsyncMock(side_effect=RuntimeError("telegram down")),
    )
    mw = ClientMenuSyncMiddleware()
    handler = AsyncMock(return_value="ok")
    msg = _private_message()

    out = await mw(handler, msg, {})
    assert out == "ok"


@pytest.mark.asyncio
async def test_menu_sync_ignores_non_private_chats(monkeypatch: pytest.MonkeyPatch) -> None:
    sync_mock = AsyncMock()
    monkeypatch.setattr(
        "src.bot.middlewares.client_menu_sync_middleware.sync_client_hub_menu_button",
        sync_mock,
    )
    mw = ClientMenuSyncMiddleware()
    handler = AsyncMock(return_value="ok")
    msg = _private_message()
    msg.chat = SimpleNamespace(id=99, type="group")

    out = await mw(handler, msg, {})
    assert out == "ok"
    sync_mock.assert_not_awaited()
