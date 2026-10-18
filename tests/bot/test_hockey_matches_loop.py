"""Цикл матчей молчит, пока флаг выключен."""

from __future__ import annotations

import asyncio

import pytest

from src.bot.notification_loops import run_hockey_matches_loop


@pytest.mark.asyncio
async def test_disabled_loop_does_not_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        return ""

    monkeypatch.setattr("src.application.hockey_matches.default_fetch", fetch)

    class _Settings:
        hockey_matches_enabled = False

    monkeypatch.setattr("src.shared.config.get_settings", lambda: _Settings())

    async def stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("src.bot.notification_loops.asyncio.sleep", stop)
    await run_hockey_matches_loop()
    assert calls == []
