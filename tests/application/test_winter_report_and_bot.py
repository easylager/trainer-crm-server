"""Сводка отчёта и цикл бота (TASK-343)."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.application import winter_marks as wm
from src.application import winter_subscriptions as wsub
from src.application.winter_report import winter_summary
from src.bot import winter_bot
from tests.application.winter_helpers import NOW, make_client, make_point


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, body, reply_markup=None):
        self.sent.append((chat_id, body))


@pytest.mark.asyncio
async def test_summary_line(db_session):
    a = await make_point(db_session, name="A")
    await make_point(db_session, name="B")
    await make_point(db_session, name="H", state="hidden")
    await wm.set_state_admin(db_session, a, "flooded", admin_id=1, now=NOW)
    s = await winter_summary(db_session, NOW)
    assert s["by_state"]["flooded"] == 1 and s["visible"] == 2
    assert s["line"].startswith("Зимой: залито 1 из 2, ждём заливку 1")


@pytest.mark.asyncio
async def test_cycle_sends_flood_summary_once(db_session, monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "1")
    monkeypatch.setattr(winter_bot, "async_session_factory", lambda: _Same(db_session))
    monkeypatch.setattr(winter_bot, "SEND_PAUSE_SEC", 0)
    a = await make_point(db_session, name="Залитый")
    await wsub.subscribe_point(db_session, 77, a)
    day = NOW - timedelta(hours=3)  # 09:00 UTC = 12:00 Минск
    await wm.set_state_admin(db_session, a, "flooded", admin_id=1, now=day - timedelta(minutes=10))
    bot = FakeBot()
    out = await winter_bot.run_winter_cycle(bot, day)
    assert out["delivery"]["sent"] == 1 and bot.sent[0][0] == 77 and "Залили" in bot.sent[0][1]
    out = await winter_bot.run_winter_cycle(bot, day + timedelta(minutes=5))
    assert out["delivery"]["sent"] == 0 and len(bot.sent) == 1


class _Same:
    """async_session_factory() -> контекст, отдающий тестовую сессию без закрытия."""

    def __init__(self, s):
        self.s = s

    async def __aenter__(self):
        return self.s

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_start_bell_subscribes_and_unknown_payload_ignored(db_session, monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "1")
    monkeypatch.setattr(winter_bot, "async_session_factory", lambda: _Same(db_session))
    a = await make_point(db_session)
    replies = []

    class Msg:
        from_user = SimpleNamespace(id=55)

        async def answer(self, text_, **kw):
            replies.append(text_)

    assert not await winter_bot.handle_winter_start(Msg(), "arena_5")
    assert await winter_bot.handle_winter_start(Msg(), f"wbell_{a}")
    assert "Готово" in replies[-1]
    assert len(await wsub.list_subscriptions(db_session, 55)) == 1
    assert await winter_bot.handle_winter_start(Msg(), "wbell_999999")
    assert "нет в списке" in replies[-1]


@pytest.mark.asyncio
async def test_site_gone_link_goes_through_bot_and_counts_only_after_confirm(db_session, monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "1")
    monkeypatch.setattr(winter_bot, "async_session_factory", lambda: _Same(db_session))
    monkeypatch.setattr(winter_bot, "_now", lambda: NOW)
    a = await make_point(db_session)
    await make_client(db_session, 77)
    replies = []

    class Msg:
        from_user = SimpleNamespace(id=77)

        async def answer(self, text_, **kw):
            replies.append((text_, kw.get("reply_markup")))

    assert await winter_bot.handle_winter_start(Msg(), f"wgone_{a}")
    assert "точки больше нет" in replies[-1][0]
    assert f"w:gone:{a}" in replies[-1][1].inline_keyboard[0][0].callback_data
    from sqlalchemy import text as sql

    count = lambda: db_session.execute(sql("SELECT count(*) FROM seasonal_rink_signals WHERE arena_id=:a"), {"a": a})  # noqa: E731
    assert (await count()).scalar_one() == 0  # одной ссылкой сигнал не засчитан

    answers = []

    class Q:
        data = f"w:gone:{a}"
        from_user = SimpleNamespace(id=77)
        message = SimpleNamespace(edit_reply_markup=lambda **kw: _noop())

        async def answer(self, text_=None, **kw):
            answers.append(text_)

    await winter_bot.on_gone_signal(Q())
    assert (await count()).scalar_one() == 1 and "передали" in answers[-1]
    assert await winter_bot.handle_winter_start(Msg(), "wgone_999999")
    assert "нет в списке" in replies[-1][0]


async def _noop():
    return None
