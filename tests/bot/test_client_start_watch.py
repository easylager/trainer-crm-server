"""TASK-328 AC7: /start watch_<arena_id> — подписка на колокольчик с сайта через бота."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.application.ice_watch_bot_start import parse_watch_start, subscribe_from_bot_start
from src.application.ice_watch_message import NBSP
from src.bot import messages as msg
from src.bot.handlers import client_handlers
from tests.api.test_public_arenas import _insert_arena, _insert_city

BASE = "https://glide.example"
MINSK = ZoneInfo("Europe/Minsk")


def _tid() -> int:
    return 7_400_000_000 + (uuid.uuid4().int % 100_000_000)


async def _future_session(db_session, arena_id: int, *, days: int):
    local_day = datetime.now(MINSK).date() + timedelta(days=days)
    starts = datetime(local_day.year, local_day.month, local_day.day, 17, 0, tzinfo=MINSK)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, status, starts_at_utc, ends_at_utc,
                starts_at_local, ends_at_local, local_date, schedule_basis, currency_code
            )
            VALUES (:aid, 'public_skate', 'active', :s, :e, '17:00', '18:00', :ld, 'live', 'BYN')
            """
        ),
        {
            "aid": arena_id,
            "s": starts.astimezone(timezone.utc),
            "e": (starts + timedelta(hours=1)).astimezone(timezone.utc),
            "ld": local_day,
        },
    )
    return local_day


async def _watches(db_session, arena_id: int) -> list[dict]:
    r = await db_session.execute(
        text(
            """
            SELECT id, telegram_id, watch_kind, active, baseline_horizon_date, filter_json
            FROM client_ice_watches WHERE arena_id = :aid
            """
        ),
        {"aid": arena_id},
    )
    return [dict(m) for m in r.mappings().all()]


def test_parse_watch_start() -> None:
    assert parse_watch_start("watch_12") == 12
    assert parse_watch_start("watch_") is None
    assert parse_watch_start("watch_12_x") is None
    assert parse_watch_start("arena_12") is None
    assert parse_watch_start(None) is None


@pytest.mark.asyncio
async def test_start_watch_creates_subscription_with_baseline(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Колокольск {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Юность")
    horizon = await _future_session(db_session, arena_id, days=2)
    tid = _tid()

    reply = await subscribe_from_bot_start(db_session, telegram_id=tid, arena_id=arena_id, webapp_base_url=BASE)
    assert reply is not None
    assert reply["text"].replace(NBSP, " ") == (
        "Готово. Напишем один раз, когда у «Юность» появится новое расписание."
    )
    assert reply["button_text"] == "Открыть «Юность»"
    assert reply["url"] == f"{BASE}/webapp/arena?arena_id={arena_id}"

    rows = await _watches(db_session, arena_id)
    assert len(rows) == 1
    assert rows[0]["telegram_id"] == tid
    assert rows[0]["watch_kind"] == "sessions"
    assert rows[0]["active"] is True
    assert rows[0]["baseline_horizon_date"] == horizon

    again = await subscribe_from_bot_start(db_session, telegram_id=tid, arena_id=arena_id, webapp_base_url=BASE)
    assert again == reply
    rows_again = await _watches(db_session, arena_id)
    assert [r["id"] for r in rows_again] == [rows[0]["id"]]


@pytest.mark.asyncio
async def test_start_watch_reopens_a_delivered_watch(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Колокольск {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Юность")
    tid = _tid()
    await subscribe_from_bot_start(db_session, telegram_id=tid, arena_id=arena_id, webapp_base_url=BASE)
    await db_session.execute(
        text("UPDATE client_ice_watches SET active = false, last_notified_at = now() WHERE arena_id = :aid"),
        {"aid": arena_id},
    )
    horizon = await _future_session(db_session, arena_id, days=4)
    await subscribe_from_bot_start(db_session, telegram_id=tid, arena_id=arena_id, webapp_base_url=BASE)
    rows = await _watches(db_session, arena_id)
    assert len(rows) == 1
    assert rows[0]["active"] is True
    assert rows[0]["baseline_horizon_date"] == horizon


@pytest.mark.asyncio
async def test_start_watch_unknown_or_hidden_rink_returns_none(app_use_test_db, db_session) -> None:
    assert (
        await subscribe_from_bot_start(db_session, telegram_id=_tid(), arena_id=999_999_999, webapp_base_url=BASE)
        is None
    )
    city_id = await _insert_city(db_session, name=f"Колокольск {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Закрытый")
    await db_session.execute(text("UPDATE arenas SET is_active = false WHERE id = :id"), {"id": arena_id})
    assert (
        await subscribe_from_bot_start(db_session, telegram_id=_tid(), arena_id=arena_id, webapp_base_url=BASE)
        is None
    )
    assert await _watches(db_session, arena_id) == []


def _message(payload: str, tid: int) -> MagicMock:
    message = MagicMock()
    message.text = f"/start {payload}"
    message.from_user = MagicMock(id=tid, username="bell_user")
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_bot_start_watch_answers_with_open_button(app_use_test_db, db_session, _test_db_core, monkeypatch) -> None:
    city_id = await _insert_city(db_session, name=f"Колокольск {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Юность")
    await db_session.commit()
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    tid = _tid()

    message = _message(f"watch_{arena_id}", tid)
    await client_handlers.cmd_start(message)
    message.answer.assert_awaited_once()
    body = message.answer.await_args.args[0]
    assert body.replace(NBSP, " ").startswith("Готово. Напишем один раз")
    markup = message.answer.await_args.kwargs["reply_markup"]
    button = markup.inline_keyboard[0][0]
    assert button.text == "Открыть «Юность»"
    assert button.web_app.url == f"{BASE}/webapp/arena?arena_id={arena_id}"

    # Повторный старт — тот же ответ, без дубля.
    second = _message(f"watch_{arena_id}", tid)
    await client_handlers.cmd_start(second)
    assert second.answer.await_args.args[0] == body
    assert len(await _watches(db_session, arena_id)) == 1


@pytest.mark.asyncio
async def test_bot_start_watch_unknown_rink_gets_plain_welcome(app_use_test_db, _test_db_core, monkeypatch) -> None:
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    message = _message("watch_999999999", _tid())
    await client_handlers.cmd_start(message)
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == msg.CLIENT_START_WELCOME
