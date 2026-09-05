"""Startup bulk restore of trainer «Обзор» menu button."""
from unittest.mock import AsyncMock, patch

import pytest

from src.bot.trainer_menu_commands import restore_all_linked_trainer_hub_menu_buttons


@pytest.mark.asyncio
async def test_restore_all_linked_trainer_hub_menu_buttons_syncs_each_chat() -> None:
    bot = AsyncMock()
    with (
        patch(
            "src.bot.trainer_menu_commands.mini_app_https_base",
            return_value=("https://app.example.com", "env"),
        ),
        patch(
            "src.bot.trainer_menu_commands.list_linked_trainer_telegram_ids_for_hub_menu",
            AsyncMock(return_value=[111, 222]),
        ),
        patch(
            "src.bot.trainer_menu_commands.sync_trainer_linked_chat_menu",
            AsyncMock(),
        ) as sync_mock,
        patch("src.bot.trainer_menu_commands.asyncio.sleep", AsyncMock()),
    ):
        await restore_all_linked_trainer_hub_menu_buttons(bot)

    assert sync_mock.await_count == 2
    sync_mock.assert_any_await(bot, 111)
    sync_mock.assert_any_await(bot, 222)


@pytest.mark.asyncio
async def test_restore_all_linked_trainer_hub_menu_buttons_skips_without_https() -> None:
    bot = AsyncMock()
    with (
        patch(
            "src.bot.trainer_menu_commands.mini_app_https_base",
            return_value=(None, "missing"),
        ),
        patch(
            "src.bot.trainer_menu_commands.sync_trainer_linked_chat_menu",
            AsyncMock(),
        ) as sync_mock,
    ):
        await restore_all_linked_trainer_hub_menu_buttons(bot)

    sync_mock.assert_not_awaited()
