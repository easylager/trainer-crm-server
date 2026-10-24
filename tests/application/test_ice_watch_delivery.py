"""TASK-328: колокольчик доставляет каждое напоминание — база подписки, проход, журнал, ошибки.

Telegram — подмена ``send_fn``: реальные сообщения не уходят.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import SendMessage
from sqlalchemy import text

from src.application import client_ice_watch_use_cases as uc
from src.application.client_ice_watch_use_cases import (
    MAX_DELIVERY_FAILURES,
    IceWatchChannelUnsupported,
    deliver_ice_watch_reminders,
    subscribe_ice_watch,
)
from src.application.ice_watch_message import NBSP
from src.infrastructure.db.models import ICE_WATCH_KIND_SEASON_OPEN, ICE_WATCH_KIND_SESSIONS

MINSK = ZoneInfo("Europe/Minsk")
_METHOD = SendMessage(chat_id=1, text="x")


def _tid() -> int:
    return 7_600_000_000 + (uuid.uuid4().int % 100_000_000)


async def _city(db_session) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group, is_active, sort_order)
            VALUES ('Bell City', 'BY', 'default', true, 0)
            RETURNING id
            """
        )
    )
    return int(r.scalar_one())


async def _arena(db_session, city_id: int, *, name: str = "Юность", tz: str = "Europe/Minsk") -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, latitude, longitude, is_active, is_confirmed, venue_type)
            VALUES (:cid, :name, 53.9, 27.5, true, true, 'ice')
            RETURNING id
            """
        ),
        {"cid": city_id, "name": name},
    )
    arena_id = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO arena_profiles (arena_id, city_id, slug, timezone, status)
            VALUES (:aid, :cid, :slug, :tz, 'published')
            """
        ),
        {"aid": arena_id, "cid": city_id, "slug": f"bell-{arena_id}", "tz": tz},
    )
    return arena_id


async def _client(db_session, telegram_id: int) -> int:
    await db_session.execute(
        text(
            "INSERT INTO client_sessions (telegram_id, state) VALUES (:tid, 'idle') "
            "ON CONFLICT (telegram_id) DO NOTHING"
        ),
        {"tid": telegram_id},
    )
    r = await db_session.execute(
        text("INSERT INTO clients (first_name, telegram_id, is_sandbox) VALUES ('Bell', :tid, false) RETURNING id"),
        {"tid": telegram_id},
    )
    return int(r.scalar_one())


async def _session(
    db_session,
    arena_id: int,
    *,
    days: int,
    hour: int = 17,
    kind: str = "public_skate",
    status: str = "active",
    tz: str = "Europe/Minsk",
) -> date:
    """Сеанс через ``days`` дней в ``hour``:00 по времени катка; возвращает его local_date."""
    zone = ZoneInfo(tz)
    local_day = datetime.now(zone).date() + timedelta(days=days)
    starts_local = datetime(local_day.year, local_day.month, local_day.day, hour, 0, tzinfo=zone)
    starts = starts_local.astimezone(timezone.utc)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, status, starts_at_utc, ends_at_utc,
                starts_at_local, ends_at_local, local_date, schedule_basis, currency_code
            )
            VALUES (:aid, :kind, :status, :start, :end, :sl, :el, :ld, 'live', 'BYN')
            """
        ),
        {
            "aid": arena_id,
            "kind": kind,
            "status": status,
            "start": starts,
            "end": starts + timedelta(hours=1),
            "sl": starts_local.time(),
            "el": (starts_local + timedelta(hours=1)).time(),
            "ld": local_day,
        },
    )
    return local_day


async def _subscribe(db_session, *, client_id: int, tid: int, arena_id: int, city_id: int, kind=ICE_WATCH_KIND_SESSIONS):
    return await subscribe_ice_watch(
        db_session,
        client_id=client_id,
        telegram_id=tid,
        arena_id=arena_id,
        watch_kind=kind,
        filter_json={"when": "any", "intent": "skate"} if kind == ICE_WATCH_KIND_SESSIONS else {},
        city_id=city_id,
    )


async def _watch_row(db_session, watch_id: int) -> dict:
    r = await db_session.execute(
        text(
            """
            SELECT active, last_notified_at, baseline_horizon_date, failed_attempts, deactivated_reason
            FROM client_ice_watches WHERE id = :id
            """
        ),
        {"id": watch_id},
    )
    return dict(r.mappings().one())


async def _journal(db_session, watch_id: int) -> list[dict]:
    r = await db_session.execute(
        text(
            """
            SELECT watch_id, client_id, arena_id, attempted_at, ok, error
            FROM client_ice_watch_deliveries WHERE watch_id = :id ORDER BY id
            """
        ),
        {"id": watch_id},
    )
    return [dict(m) for m in r.mappings().all()]


async def _setup(db_session, *, name: str = "Юность"):
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, name=name)
    tid = _tid()
    client_id = await _client(db_session, tid)
    return city_id, arena_id, tid, client_id


async def _pass(db_session, send) -> uc.IceWatchPassStats:
    return await deliver_ice_watch_reminders(db_session, now=datetime.now(timezone.utc), send_fn=send)


# --- AC1: база подписки ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_baseline_is_latest_future_public_session_date(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    await _session(db_session, arena_id, days=1)
    last = await _session(db_session, arena_id, days=3)
    # Не учитываются: другой вид, отменённый, прошедший.
    await _session(db_session, arena_id, days=6, kind="hockey_practice")
    await _session(db_session, arena_id, days=7, status="cancelled")
    await _session(db_session, arena_id, days=-1)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    assert (await _watch_row(db_session, watch["id"]))["baseline_horizon_date"] == last


@pytest.mark.asyncio
async def test_baseline_null_on_empty_card(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    assert (await _watch_row(db_session, watch["id"]))["baseline_horizon_date"] is None


@pytest.mark.asyncio
async def test_no_false_fire_on_non_empty_card(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    await _session(db_session, arena_id, days=1)
    await _session(db_session, arena_id, days=2)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    send = AsyncMock()
    await _pass(db_session, send)
    send.assert_not_awaited()
    row = await _watch_row(db_session, watch["id"])
    assert row["active"] is True
    assert await _journal(db_session, watch["id"]) == []


@pytest.mark.asyncio
async def test_new_dates_past_baseline_fire_once_with_new_range(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    await _session(db_session, arena_id, days=1)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    # Каток выложил ещё неделю; плюс добавил сеанс в уже известный день — он не «новый».
    await _session(db_session, arena_id, days=1, hour=20)
    first = await _session(db_session, arena_id, days=8, hour=17)
    last = await _session(db_session, arena_id, days=14, hour=12)
    send = AsyncMock()
    stats = await _pass(db_session, send)
    assert stats.sent == 1
    send.assert_awaited_once()
    chat_id, body, _markup = send.await_args.args
    assert chat_id == tid
    plain = body.replace(NBSP, " ")
    assert plain.startswith("<b>«Юность»: новое расписание</b>\n")
    assert f"{first.day} " in plain and f"{last.day} " in plain
    assert "17:00" in plain
    assert "20:00" not in plain


@pytest.mark.asyncio
async def test_empty_card_fires_on_any_future_session(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    send = AsyncMock()
    await _pass(db_session, send)
    send.assert_not_awaited()
    await _session(db_session, arena_id, days=1, hour=23)
    await _pass(db_session, send)
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_reopened_watch_takes_new_baseline(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    await _session(db_session, arena_id, days=2)
    send = AsyncMock()
    await _pass(db_session, send)
    assert send.await_count == 1
    # Повторная подписка после доставки: то, что уже на карточке, — не новое.
    again = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    assert again["id"] == watch["id"]
    row = await _watch_row(db_session, watch["id"])
    assert row["active"] is True and row["baseline_horizon_date"] is not None
    await _pass(db_session, send)
    assert send.await_count == 1


# --- AC3 / AC9: журнал и отсутствие дублей ---------------------------------------------


@pytest.mark.asyncio
async def test_success_journal_and_deactivation(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    await _session(db_session, arena_id, days=2)
    send = AsyncMock()
    await _pass(db_session, send)
    row = await _watch_row(db_session, watch["id"])
    assert row["active"] is False
    assert row["last_notified_at"] is not None
    assert row["deactivated_reason"] is None
    journal = await _journal(db_session, watch["id"])
    assert len(journal) == 1
    assert journal[0]["ok"] is True and journal[0]["error"] is None
    assert journal[0]["client_id"] == client_id and journal[0]["arena_id"] == arena_id


@pytest.mark.asyncio
async def test_two_passes_in_a_row_send_once(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    await _session(db_session, arena_id, days=2)
    send = AsyncMock()
    await _pass(db_session, send)
    await _pass(db_session, send)
    assert send.await_count == 1
    assert len(await _journal(db_session, watch["id"])) == 1


@pytest.mark.asyncio
async def test_failure_after_send_resends_once_then_stops(db_session, monkeypatch) -> None:
    """At-least-once: сбой между отправкой и пометкой → один повтор, а не дубль на каждом проходе."""
    city_id, arena_id, tid, client_id = await _setup(db_session)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    await _session(db_session, arena_id, days=2)
    await db_session.commit()

    real_mark = uc.ClientIceWatchRepository.mark_notified_and_deactivate
    calls = {"n": 0}

    async def flaky_mark(self, watch_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("db went away after send")
        return await real_mark(self, watch_id)

    monkeypatch.setattr(uc.ClientIceWatchRepository, "mark_notified_and_deactivate", flaky_mark)
    send = AsyncMock()
    await _pass(db_session, send)
    assert send.await_count == 1
    assert (await _watch_row(db_session, watch["id"]))["active"] is True

    await _pass(db_session, send)
    await _pass(db_session, send)
    assert send.await_count == 2
    row = await _watch_row(db_session, watch["id"])
    assert row["active"] is False and row["last_notified_at"] is not None


# --- AC4: недоступный чат и повторы ----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        TelegramForbiddenError(_METHOD, "Forbidden: bot was blocked by the user"),
        TelegramForbiddenError(_METHOD, "Forbidden: user is deactivated"),
        TelegramBadRequest(_METHOD, "Bad Request: chat not found"),
    ],
)
async def test_unreachable_chat_deactivates_with_reason(db_session, exc) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    await _session(db_session, arena_id, days=2)
    send = AsyncMock(side_effect=exc)
    stats = await _pass(db_session, send)
    assert stats.unreachable == 1
    row = await _watch_row(db_session, watch["id"])
    assert row["active"] is False
    assert row["deactivated_reason"] == "unreachable"
    assert row["last_notified_at"] is None
    journal = await _journal(db_session, watch["id"])
    assert len(journal) == 1 and journal[0]["ok"] is False
    assert str(tid) not in (journal[0]["error"] or "")
    await _pass(db_session, send)
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_transient_failures_retry_then_give_up_after_five(db_session, caplog) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    await _session(db_session, arena_id, days=2)
    send = AsyncMock(side_effect=TelegramNetworkError(_METHOD, f"timeout talking to chat {tid}"))
    caplog.set_level(logging.WARNING, logger=uc.logger.name)

    for attempt in range(1, MAX_DELIVERY_FAILURES):
        await _pass(db_session, send)
        row = await _watch_row(db_session, watch["id"])
        assert row["active"] is True, attempt
        assert row["failed_attempts"] == attempt
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    await _pass(db_session, send)
    row = await _watch_row(db_session, watch["id"])
    assert row["active"] is False
    assert row["deactivated_reason"] == "failed"
    assert send.await_count == MAX_DELIVERY_FAILURES == 5
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and f"watch_id={watch['id']}" in errors[0].getMessage()
    journal = await _journal(db_session, watch["id"])
    assert [j["ok"] for j in journal] == [False] * 5
    assert all(str(tid) not in (j["error"] or "") for j in journal)

    await _pass(db_session, send)
    assert send.await_count == 5


@pytest.mark.asyncio
async def test_transient_failure_then_success_delivers(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    watch = await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    await _session(db_session, arena_id, days=2)
    send = AsyncMock(side_effect=[RuntimeError("telegram 502"), None])
    await _pass(db_session, send)
    await _pass(db_session, send)
    row = await _watch_row(db_session, watch["id"])
    assert row["active"] is False and row["last_notified_at"] is not None
    assert [j["ok"] for j in await _journal(db_session, watch["id"])] == [False, True]


# --- AC5: суррогатный id MAX ----------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_rejects_max_surrogate_telegram_id(db_session) -> None:
    city_id, arena_id, _tid_unused, _ = await _setup(db_session)
    surrogate = -(10**12 + 12345)
    client_id = await _client(db_session, surrogate)
    with pytest.raises(IceWatchChannelUnsupported):
        await _subscribe(db_session, client_id=client_id, tid=surrogate, arena_id=arena_id, city_id=city_id)


@pytest.mark.asyncio
async def test_legacy_surrogate_watch_is_closed_without_sending(db_session) -> None:
    city_id, arena_id, _tid_unused, _ = await _setup(db_session)
    surrogate = -(10**12 + 54321)
    client_id = await _client(db_session, surrogate)
    r = await db_session.execute(
        text(
            """
            INSERT INTO client_ice_watches (client_id, telegram_id, arena_id, watch_kind, filter_json, active)
            VALUES (:cid, :tg, :aid, 'sessions', '{}'::jsonb, true) RETURNING id
            """
        ),
        {"cid": client_id, "tg": surrogate, "aid": arena_id},
    )
    watch_id = int(r.scalar_one())
    await _session(db_session, arena_id, days=2)
    send = AsyncMock()
    await _pass(db_session, send)
    send.assert_not_awaited()
    row = await _watch_row(db_session, watch_id)
    assert row["active"] is False and row["deactivated_reason"] == "unreachable"


# --- AC8: season_open как раньше -------------------------------------------------------


@pytest.mark.asyncio
async def test_pass_clears_season_open_when_sessions_exist(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    season = await _subscribe(
        db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id, kind=ICE_WATCH_KIND_SEASON_OPEN
    )
    send = AsyncMock()
    await _pass(db_session, send)
    assert (await _watch_row(db_session, season["id"]))["active"] is True
    await _session(db_session, arena_id, days=2)
    await _pass(db_session, send)
    send.assert_not_awaited()
    row = await _watch_row(db_session, season["id"])
    assert row["active"] is False and row["last_notified_at"] is None


# --- AC6: таймзона катка ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_dates_in_rink_timezone(db_session) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, name="Айсбург", tz="Asia/Yekaterinburg")
    tid = _tid()
    client_id = await _client(db_session, tid)
    await _subscribe(db_session, client_id=client_id, tid=tid, arena_id=arena_id, city_id=city_id)
    local_day = await _session(db_session, arena_id, days=1, hour=23, tz="Asia/Yekaterinburg")
    send = AsyncMock()
    await _pass(db_session, send)
    body = send.await_args.args[1].replace(NBSP, " ")
    assert f"Сеансы на {local_day.day} " in body
    assert "Ближайший — завтра в 23:00." in body
