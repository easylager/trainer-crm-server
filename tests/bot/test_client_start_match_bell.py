"""TASK-347: /start mbell_<матч> и кнопка «Отписаться»."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from src.bot import messages as msg
from src.bot.handlers import client_handlers
from tests.api.test_site_matches import _flags, _match, _world  # noqa: F401
from tests.bot.test_client_start_watch import BASE, _message, _tid


@pytest.mark.asyncio
async def test_start_bell_subscribes_once_and_unsubscribes(app_use_test_db, db_session, _test_db_core, monkeypatch):
    await _world(db_session)
    mid = await _match(db_session, starts=datetime.now(timezone.utc) + timedelta(days=2))
    await db_session.commit()
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    tid = _tid()
    first = _message(f"mbell_{mid}", tid)
    await client_handlers.cmd_start(first)
    body = first.answer.await_args.args[0]
    assert body.startswith("Готово: напомним о матче")
    buttons = [b for row in first.answer.await_args.kwargs["reply_markup"].inline_keyboard for b in row]
    assert any(b.callback_data == f"mbell_off:{mid}" for b in buttons)
    second = _message(f"mbell_{mid}", tid)
    await client_handlers.cmd_start(second)
    assert second.answer.await_args.args[0].startswith("Уже стоит")
    n = (await db_session.execute(text("SELECT COUNT(*) FROM hockey_match_bells WHERE telegram_id=:t"), {"t": tid})).scalar_one()
    assert n == 1

    cb = MagicMock(data=f"mbell_off:{mid}", from_user=SimpleNamespace(id=tid))
    cb.answer = AsyncMock()
    cb.message = MagicMock(edit_reply_markup=AsyncMock())
    await client_handlers.match_bell_off_callback(cb)
    cb.answer.assert_awaited_with("Напоминание снято")
    await client_handlers.match_bell_off_callback(cb)
    cb.answer.assert_awaited_with("Уже отключено")


@pytest.mark.asyncio
async def test_start_bell_unknown_match_gets_welcome(app_use_test_db, _test_db_core, monkeypatch):
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    message = _message("mbell_99999999", _tid())
    await client_handlers.cmd_start(message)
    assert message.answer.await_args.args[0] == msg.CLIENT_START_WELCOME
