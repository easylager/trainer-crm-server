"""Кнопка «Отменить рассылку» под уведомлением о смене расписания."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from src.application.client_ice_watch_use_cases import _change_notice_markup_factory, subscribe_ice_watch
from src.application.ice_watch_message import CANCEL_WATCH_BUTTON, OPEN_SCHEDULE_BUTTON, watch_off_callback_data
from src.bot.handlers import client_handlers
from src.infrastructure.db.models import ICE_WATCH_KIND_SESSIONS
from tests.bot.test_client_start_watch import _tid
from tests.api.test_public_arenas import _insert_arena, _insert_city


@pytest.mark.asyncio
async def test_change_notice_markup_has_open_and_cancel() -> None:
    https = _change_notice_markup_factory("https://app.example")
    kb = https(9, 42)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert texts == [OPEN_SCHEDULE_BUTTON, CANCEL_WATCH_BUTTON]
    assert kb.inline_keyboard[0][0].web_app.url.endswith("/webapp/arena?arena_id=9")
    assert kb.inline_keyboard[1][0].callback_data == watch_off_callback_data(42)

    http_only = _change_notice_markup_factory("http://127.0.0.1:8000")
    kb2 = http_only(9, 42)
    assert [b.text for row in kb2.inline_keyboard for b in row] == [CANCEL_WATCH_BUTTON]

    # One-shot schedule_fresh: открыть расписание без «Отменить» — подписка гаснет сама.
    fresh = _change_notice_markup_factory("https://app.example", cancel=False)
    assert [b.text for row in fresh(9, 42).inline_keyboard for b in row] == [OPEN_SCHEDULE_BUTTON]


@pytest.mark.asyncio
async def test_ice_watch_off_callback_deactivates(
    app_use_test_db, db_session, _test_db_core, monkeypatch
) -> None:
    city_id = await _insert_city(db_session, name="Минск")
    arena_id = await _insert_arena(db_session, city_id, name="Юность")
    tid = _tid()
    await db_session.execute(
        text(
            "INSERT INTO client_sessions (telegram_id, state) VALUES (:tid, 'idle') "
            "ON CONFLICT (telegram_id) DO NOTHING"
        ),
        {"tid": tid},
    )
    client_id = int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO clients (first_name, telegram_id, is_sandbox) "
                    "VALUES ('Bell', :tid, false) RETURNING id"
                ),
                {"tid": tid},
            )
        ).scalar_one()
    )
    watch = await subscribe_ice_watch(
        db_session,
        client_id=client_id,
        telegram_id=tid,
        arena_id=arena_id,
        watch_kind=ICE_WATCH_KIND_SESSIONS,
        filter_json={"when": "any", "intent": "skate"},
        city_id=city_id,
    )
    await db_session.commit()
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])

    cb = MagicMock(data=watch_off_callback_data(int(watch["id"])), from_user=SimpleNamespace(id=tid))
    cb.answer = AsyncMock()
    cb.message = MagicMock(edit_reply_markup=AsyncMock())
    await client_handlers.ice_watch_off_callback(cb)
    cb.answer.assert_awaited_with("Рассылку отключили")
    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    active = (
        await db_session.execute(
            text("SELECT active FROM client_ice_watches WHERE id = :id"), {"id": watch["id"]}
        )
    ).scalar_one()
    assert active is False

    await client_handlers.ice_watch_off_callback(cb)
    cb.answer.assert_awaited_with("Уже отключено")
