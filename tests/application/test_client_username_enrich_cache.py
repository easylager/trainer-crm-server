"""Lists never wait for getChat; an empty answer is remembered (TASK-314)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.application import client_username_enrich as enrich


class _FakeBot:
    def __init__(self, usernames: dict[int, str | None]) -> None:
        self.usernames = usernames
        self.calls: list[int] = []
        self.session = SimpleNamespace(close=self._close)

    async def _close(self) -> None:
        return None

    async def get_chat(self, uid: int):
        self.calls.append(uid)
        return SimpleNamespace(username=self.usernames.get(uid))


@pytest.fixture(autouse=True)
def _clean_state():
    enrich._checked_without_username.clear()
    enrich._in_flight.clear()
    yield
    enrich._checked_without_username.clear()
    enrich._in_flight.clear()


class _NoDb:
    async def execute(self, *_a, **_k):
        return None


@pytest.mark.asyncio
async def test_single_card_asks_once_and_remembers_no_username(monkeypatch) -> None:
    bot = _FakeBot({501: None})
    monkeypatch.setattr(enrich, "_client_bot", lambda: bot)
    row = {"client_telegram_id": 501, "client_telegram_username": ""}
    await enrich.enrich_booking_dicts_with_client_telegram_usernames(_NoDb(), [row])
    await enrich.enrich_booking_dicts_with_client_telegram_usernames(_NoDb(), [dict(row)])
    assert bot.calls == [501]


@pytest.mark.asyncio
async def test_single_card_gets_the_username_inline(monkeypatch) -> None:
    bot = _FakeBot({502: "olga_k"})
    monkeypatch.setattr(enrich, "_client_bot", lambda: bot)
    row = {"client_telegram_id": 502, "client_telegram_username": None}
    await enrich.enrich_booking_dicts_with_client_telegram_usernames(_NoDb(), [row])
    assert row["client_telegram_username"] == "olga_k"


@pytest.mark.asyncio
async def test_list_returns_without_waiting_for_telegram(monkeypatch) -> None:
    started: list[list[int]] = []
    gate = asyncio.Event()

    async def slow_refresh(uids: list[int]) -> None:
        started.append(uids)
        await gate.wait()
        enrich._in_flight.difference_update(uids)

    monkeypatch.setattr(enrich, "_refresh_in_background", slow_refresh)
    monkeypatch.setattr(enrich, "_client_bot_configured", lambda: True)
    rows = [{"client_telegram_id": uid} for uid in (601, 602, 603)]
    await asyncio.wait_for(
        enrich.enrich_booking_dicts_with_client_telegram_usernames(_NoDb(), rows), timeout=0.5
    )
    await asyncio.sleep(0)
    assert started == [[601, 602, 603]]
    # The same list opened again while the refresh runs does not start a second one.
    await enrich.enrich_booking_dicts_with_client_telegram_usernames(_NoDb(), rows)
    await asyncio.sleep(0)
    assert len(started) == 1
    gate.set()
