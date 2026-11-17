"""TASK-428: «Не присылать» / «Присылать», подписка из напоминания и ``/start watch_<id>_o`` из предложения."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message
from sqlalchemy import text

from src.application.catalog_consumer_events import telegram_actor_hash
from src.application.ice_watch_bot_start import parse_watch_start, watch_start_origin
from src.application.place_links import is_offer_watch_start, watch_start_param
from src.bot.handlers import client_handlers
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.bot.test_client_start_watch import _message, _tid

BASE = "https://glide.example"
SECRET = "s" * 40


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", SECRET)


def _cb(data: str, tid: int, *, accessible: bool = True) -> MagicMock:
    cb = MagicMock(data=data, from_user=SimpleNamespace(id=tid, username="u"))
    cb.answer = AsyncMock()
    # Telegram отдаёт InaccessibleMessage вместо Message, если сообщение старое: его не правим.
    cb.message = MagicMock(spec=Message) if accessible else MagicMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


async def _events(db, arena_id: int) -> list[tuple]:
    rows = await db.execute(
        text("SELECT kind, surface, actor_hash FROM catalog_consumer_events WHERE arena_id = :a ORDER BY id"),
        {"a": arena_id},
    )
    return [tuple(r) for r in rows.all()]


def test_offer_start_param() -> None:
    assert watch_start_param(12, offer=True) == "watch_12_o"
    assert parse_watch_start("watch_12_o") == 12 and is_offer_watch_start("watch_12_o")
    assert watch_start_origin("watch_12_o") == "offer" and watch_start_origin("watch_12") is None
    for bad in ("watch_12_x", "watch_0_o", "watch__o", "watch_12_oo", None):
        assert not is_offer_watch_start(bad)


@pytest.mark.asyncio
async def test_opt_out_and_back(app_use_test_db, db_session, _test_db_core, monkeypatch) -> None:
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    tid = _tid()
    off = _cb("warm:off", tid)
    await client_handlers.warm_opt_callback(off)
    row = (
        await db_session.execute(text("SELECT opted_out_at FROM warm_prefs WHERE telegram_id = :k"), {"k": tid})
    ).one()
    assert row.opted_out_at is not None
    assert off.answer.await_args.kwargs["show_alert"] is True
    markup = off.message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert [b.callback_data for r in markup.inline_keyboard for b in r] == ["warm:on"]

    on = _cb("warm:on", tid)
    await client_handlers.warm_opt_callback(on)
    row = (
        await db_session.execute(text("SELECT opted_out_at FROM warm_prefs WHERE telegram_id = :k"), {"k": tid})
    ).one()
    assert row.opted_out_at is None


@pytest.mark.asyncio
async def test_subscribe_from_nudge_records_funnel(app_use_test_db, db_session, _test_db_core, monkeypatch) -> None:
    city_id = await _insert_city(db_session, name="Минск")
    arena_id = await _insert_arena(db_session, city_id, name="Юность")
    await db_session.commit()
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    tid = _tid()
    await db_session.execute(
        text("INSERT INTO warm_prefs (telegram_id, bot_blocked_at) VALUES (:k, now())"), {"k": tid}
    )
    cb = _cb(f"warm:sub:{arena_id}", tid)
    await client_handlers.warm_subscribe_callback(cb)
    active = (
        await db_session.execute(
            text("SELECT active FROM client_ice_watches WHERE telegram_id = :k AND arena_id = :a"),
            {"k": tid, "a": arena_id},
        )
    ).scalar_one()
    assert active is True
    assert await _events(db_session, arena_id) == [("watch_offer_subscribed", "warm_nudge", telegram_actor_hash(tid))]
    cb.message.answer.assert_awaited_once()
    blocked = (
        await db_session.execute(text("SELECT bot_blocked_at FROM warm_prefs WHERE telegram_id = :k"), {"k": tid})
    ).scalar_one()
    assert blocked is None  # сам подписался — блокировка прогрева снята


@pytest.mark.asyncio
async def test_subscribe_from_nudge_unknown_arena(app_use_test_db, _test_db_core, monkeypatch) -> None:
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    cb = _cb("warm:sub:999999999", _tid())
    await client_handlers.warm_subscribe_callback(cb)
    assert cb.answer.await_args.args[0] == "Этого катка больше нет в каталоге."


@pytest.mark.asyncio
async def test_start_from_offer_records_subscription(app_use_test_db, db_session, _test_db_core, monkeypatch) -> None:
    city_id = await _insert_city(db_session, name="Минск")
    arena_id = await _insert_arena(db_session, city_id, name="Юность")
    plain_arena = await _insert_arena(db_session, city_id, name="Чижовка")
    await db_session.commit()
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    tid = _tid()
    await client_handlers.cmd_start(_message(f"watch_{arena_id}_o", tid))
    await client_handlers.cmd_start(_message(f"watch_{plain_arena}", tid))
    assert await _events(db_session, arena_id) == [("watch_offer_subscribed", "place_page", telegram_actor_hash(tid))]
    assert await _events(db_session, plain_arena) == []  # обычный колокольчик в воронку предложения не пишется


@pytest.mark.asyncio
async def test_inaccessible_message_is_not_edited(app_use_test_db, _test_db_core, monkeypatch) -> None:
    """Ревью п. 12: старое сообщение (InaccessibleMessage) — ответ во всплывающем окне, без правки кнопок."""
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    cb = _cb("warm:off", _tid(), accessible=False)
    await client_handlers.warm_opt_callback(cb)
    cb.answer.assert_awaited_once()
    cb.message.edit_reply_markup.assert_not_awaited()
