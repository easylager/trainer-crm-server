"""TrainerMenuSyncMiddleware: «Обзор» menu button must stay in sync for linked chats."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from src.bot.middlewares.trainer_menu_sync_middleware import TrainerMenuSyncMiddleware
import time


class _FakeSessionCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def patch_menu_sync_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.bot.middlewares.trainer_menu_sync_middleware.async_session_factory",
        lambda: _FakeSessionCM(),
    )


def _private_message(uid: int = 42, chat_id: int = 99) -> Message:
    msg = MagicMock(spec=Message)
    msg.from_user = SimpleNamespace(id=uid)
    msg.chat = SimpleNamespace(id=chat_id, type="private")
    msg.bot = SimpleNamespace()
    return msg


@pytest.mark.asyncio
async def test_menu_sync_always_runs_for_linked_even_when_recent(
    monkeypatch: pytest.MonkeyPatch, patch_menu_sync_session
) -> None:
    sync_mock = AsyncMock()
    monkeypatch.setattr(
        "src.bot.middlewares.trainer_menu_sync_middleware.get_trainer_id_by_telegram_id",
        AsyncMock(return_value=7),
    )
    monkeypatch.setattr(
        "src.bot.middlewares.trainer_menu_sync_middleware.sync_trainer_linked_chat_menu",
        sync_mock,
    )
    mw = TrainerMenuSyncMiddleware()
    mw._last_sig[42] = "linked"
    mw._last_time[42] = time.monotonic()

    handler = AsyncMock(return_value="ok")
    msg = _private_message()

    out = await mw(handler, msg, {})
    assert out == "ok"
    sync_mock.assert_awaited_once_with(msg.bot, 99)


@pytest.mark.asyncio
async def test_menu_sync_skips_reset_for_unlinked_when_throttled(
    monkeypatch: pytest.MonkeyPatch, patch_menu_sync_session
) -> None:
    reset_mock = AsyncMock()
    monkeypatch.setattr(
        "src.bot.middlewares.trainer_menu_sync_middleware.get_trainer_id_by_telegram_id",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.bot.middlewares.trainer_menu_sync_middleware.reset_trainer_menu_for_unlinked",
        reset_mock,
    )
    mw = TrainerMenuSyncMiddleware()
    mw._last_sig[42] = "unlinked"
    mw._last_time[42] = time.monotonic()

    handler = AsyncMock(return_value="ok")
    msg = _private_message()

    await mw(handler, msg, {})
    reset_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_menu_sync_db_failure_does_not_reset_menu(
    monkeypatch: pytest.MonkeyPatch, patch_menu_sync_session
) -> None:
    reset_mock = AsyncMock()
    sync_mock = AsyncMock()
    monkeypatch.setattr(
        "src.bot.middlewares.trainer_menu_sync_middleware.get_trainer_id_by_telegram_id",
        AsyncMock(side_effect=RuntimeError("db down")),
    )
    monkeypatch.setattr(
        "src.bot.middlewares.trainer_menu_sync_middleware.reset_trainer_menu_for_unlinked",
        reset_mock,
    )
    monkeypatch.setattr(
        "src.bot.middlewares.trainer_menu_sync_middleware.sync_trainer_linked_chat_menu",
        sync_mock,
    )
    mw = TrainerMenuSyncMiddleware()
    handler = AsyncMock(return_value="ok")
    msg = _private_message()

    out = await mw(handler, msg, {})
    assert out == "ok"
    reset_mock.assert_not_awaited()
    sync_mock.assert_not_awaited()
