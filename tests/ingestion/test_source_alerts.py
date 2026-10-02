"""TASK-146: пуш в админ-бот по конкретной арене — алерт, напоминание, «восстановлено»."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from src.ingestion.alerts import send_ice_health_to_admins
from src.ingestion.source_alerts import (
    KIND_FAILING,
    KIND_RECOVERED,
    KIND_REMINDER,
    SourceHealthRow,
    chunk_messages,
    decide_source_alerts,
    format_source_alert,
    tick_source_failure_alerts,
)

# 13:00 по Минску.
_NOW = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def _row(**overrides) -> SourceHealthRow:
    base = SourceHealthRow(
        job_id=1,
        arena_id=10,
        arena_name="Минск-Арена",
        city_name="Минск",
        parser_key="minskarena_saleframe_v1",
        is_enabled=True,
        config={},
        created_at=_NOW - timedelta(days=30),
        last_run_at=_NOW,
        last_ok_at=_NOW - timedelta(hours=1),
        last_ok_slot_count=12,
        failing_since=_NOW - timedelta(minutes=20),
        failure_streak=2,
        last_error_code="extract_error",
        last_error_summary="HTTP 503 Service Unavailable",
        alert_state="ok",
        alert_sent_at=None,
        shown_sessions=12,
        shown_observed_at=_NOW - timedelta(hours=1),
    )
    return replace(base, **overrides)


# ── Чистые правила ───────────────────────────────────────────────────────


def test_alert_message_says_what_failed_since_when_and_what_users_see() -> None:
    body = format_source_alert(_row(), kind=KIND_FAILING, now=_NOW)
    assert body.startswith("🔴")
    assert "Минск-Арена (Минск)" in body
    assert "minskarena_saleframe_v1" in body
    assert "парсер упал при чтении сайта" in body
    assert "HTTP 503" in body
    assert "С: 1 окт, 12:40" in body
    assert "попыток подряд: 2" in body
    assert "Пользователи видят: расписание от 1 окт, 12:00 — 12 сеансов" in body


def test_single_failure_does_not_alert() -> None:
    assert decide_source_alerts([_row(failure_streak=1)], now=_NOW) == []


def test_transition_reminder_and_recovery() -> None:
    [first] = decide_source_alerts([_row()], now=_NOW)
    assert first.kind == KIND_FAILING

    failing = _row(alert_state="failing", alert_sent_at=_NOW)
    assert decide_source_alerts([failing], now=_NOW + timedelta(minutes=2)) == []
    assert decide_source_alerts([failing], now=_NOW + timedelta(hours=3)) == []
    [reminder] = decide_source_alerts([failing], now=_NOW + timedelta(hours=4))
    assert reminder.kind == KIND_REMINDER
    assert reminder.text.startswith("🟠")
    # Ночью (01:00 по Минску) напоминания не будят админа.
    assert decide_source_alerts([failing], now=_NOW + timedelta(hours=12)) == []

    healed = replace(failing, failure_streak=0, failing_since=None, last_error_code=None, last_ok_at=_NOW)
    [recovered] = decide_source_alerts([healed], now=_NOW + timedelta(hours=1))
    assert recovered.kind == KIND_RECOVERED
    assert recovered.text.startswith("✅ Лёд: источник восстановлен")
    assert "Пользователи видят: расписание от" in recovered.text


def test_stale_without_errors_alerts_only_when_users_see_sessions() -> None:
    stale = _row(
        failure_streak=0,
        failing_since=None,
        last_error_code=None,
        last_error_summary=None,
        last_ok_at=_NOW - timedelta(hours=8),
    )
    [alert] = decide_source_alerts([stale], now=_NOW)
    assert "не подтверждалось" in alert.text
    assert "Последний успешный прогон: 1 окт, 05:00" in alert.text
    assert decide_source_alerts([replace(stale, shown_sessions=0)], now=_NOW) == []


def test_muted_or_disabled_source_does_not_alert_and_clears_open_alert() -> None:
    assert decide_source_alerts([_row(config={"alerts_muted": True})], now=_NOW) == []
    [cleared] = decide_source_alerts(
        [_row(is_enabled=False, alert_state="failing", alert_sent_at=_NOW)], now=_NOW
    )
    assert cleared.kind == KIND_RECOVERED
    assert "выключен" in cleared.text


def test_empty_after_slots_and_empty_storefront_wording() -> None:
    body = format_source_alert(
        _row(
            last_error_code="empty_after_slots",
            last_error_summary="источник вернул 0 сеансов, а у нас показано 1",
            shown_sessions=1,
        ),
        kind=KIND_FAILING,
        now=_NOW,
    )
    assert "источник вернул 0 сеансов, а у нас показано 1" in body
    assert "— 1 сеанс" in body
    nothing = format_source_alert(_row(shown_sessions=0), kind=KIND_FAILING, now=_NOW)
    assert "расписания нет" in nothing


def test_many_arenas_in_one_tick_fit_into_few_messages() -> None:
    rows = [_row(job_id=i, arena_name=f"Арена {i}") for i in range(1, 41)]
    alerts = decide_source_alerts(rows, now=_NOW)
    chunks = chunk_messages([a.text for a in alerts])
    assert len(alerts) == 40
    assert 1 < len(chunks) < 10
    assert all(len(c) <= 3800 for c in chunks)
    assert sum(c.count("🔴") for c in chunks) == 40


# ── Тик на реальной БД, Telegram замокан ─────────────────────────────────


async def _setup_failing_source(db_session) -> tuple[int, int]:
    city = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                "VALUES ('AlertCity', 'BY', 'BY_BASE', true, 9300) RETURNING id"
            )
        )
    ).scalar_one()
    arena_id = int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO arenas (city_id, name, address, is_active, is_confirmed) "
                    "VALUES (:cid, 'Каток Алерт', 'ул. 1', true, true) RETURNING id"
                ),
                {"cid": city},
            )
        ).scalar_one()
    )
    job_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs (
                        arena_id, parser_key, is_enabled, cadence, next_run_at, config,
                        last_ok_at, last_ok_slot_count, failing_since, failure_streak,
                        last_error_code, last_error_summary
                    ) VALUES (
                        :aid, 'alert_test_v1', true, 'daily', :now, CAST(:cfg AS jsonb),
                        :ok, 3, :since, 3, 'validation_error', 'starts_at_local is required'
                    ) RETURNING id
                    """
                ),
                {
                    "aid": arena_id,
                    "now": _NOW,
                    "cfg": json.dumps({}),
                    "ok": _NOW - timedelta(hours=2),
                    "since": _NOW - timedelta(minutes=45),
                },
            )
        ).scalar_one()
    )
    for i in range(3):
        starts = _NOW + timedelta(days=2, hours=i)
        await db_session.execute(
            text(
                """
                INSERT INTO ice_sessions (arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                    starts_at_local, ends_at_local, currency_code, status, source_id, observed_at)
                VALUES (:aid, 'public_skate', :s, :e, :d, :st, :et, 'BYN', 'active', :sid, :obs)
                """
            ),
            {
                "aid": arena_id,
                "s": starts,
                "e": starts + timedelta(minutes=45),
                "d": starts.date(),
                "st": starts.time(),
                "et": (starts + timedelta(minutes=45)).time(),
                "sid": f"run:1:{i}",
                "obs": _NOW - timedelta(hours=2),
            },
        )
    return arena_id, job_id


async def _alert_state(db_session, job_id: int):
    return (
        await db_session.execute(
            text("SELECT alert_state, alert_sent_at FROM ice_parser_jobs WHERE id = :id"),
            {"id": job_id},
        )
    ).one()


def _texts_for(sender: AsyncMock, needle: str) -> list[str]:
    return [c.args[0] for c in sender.await_args_list if needle in c.args[0]]


@pytest.mark.asyncio
async def test_tick_sends_once_reminds_later_and_reports_recovery(db_session) -> None:
    _arena_id, job_id = await _setup_failing_source(db_session)
    sender = AsyncMock()

    await tick_source_failure_alerts(db_session, now=_NOW, sender=sender)
    [body] = _texts_for(sender, "Каток Алерт")
    assert body.startswith("🔴 Лёд: сломался источник")
    assert "alert_test_v1" in body
    assert "данные с сайта не прошли проверку" in body
    assert "С: 1 окт, 12:15" in body
    assert "Пользователи видят: расписание от 1 окт, 11:00 — 3 сеанса" in body
    assert sender.await_args.kwargs["event"] == "ice source alert"
    state = await _alert_state(db_session, job_id)
    assert (state.alert_state, state.alert_sent_at) == ("failing", _NOW)

    # Тот же сбой через 2 минуты и через 3 часа — тишина.
    sender.reset_mock()
    await tick_source_failure_alerts(db_session, now=_NOW + timedelta(minutes=2), sender=sender)
    await tick_source_failure_alerts(db_session, now=_NOW + timedelta(hours=3), sender=sender)
    assert _texts_for(sender, "Каток Алерт") == []

    # Через 4 часа — одно напоминание.
    await tick_source_failure_alerts(db_session, now=_NOW + timedelta(hours=4), sender=sender)
    [reminder] = _texts_for(sender, "Каток Алерт")
    assert reminder.startswith("🟠")

    # Парсер починился — «восстановлено» один раз.
    sender.reset_mock()
    await db_session.execute(
        text(
            "UPDATE ice_parser_jobs SET failure_streak = 0, failing_since = NULL, "
            "last_error_code = NULL, last_error_summary = NULL, last_ok_at = :ok WHERE id = :id"
        ),
        {"ok": _NOW + timedelta(hours=5), "id": job_id},
    )
    await tick_source_failure_alerts(db_session, now=_NOW + timedelta(hours=5), sender=sender)
    [recovered] = _texts_for(sender, "Каток Алерт")
    assert recovered.startswith("✅")
    assert (await _alert_state(db_session, job_id)).alert_state == "ok"
    sender.reset_mock()
    await tick_source_failure_alerts(db_session, now=_NOW + timedelta(hours=6), sender=sender)
    assert _texts_for(sender, "Каток Алерт") == []


# ── Доставка в админ-бот ─────────────────────────────────────────────────


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.session = SimpleNamespace(close=AsyncMock())

    async def send_message(self, *, chat_id: int, text: str, disable_web_page_preview: bool) -> None:
        self.sent.append((chat_id, text))


@pytest.mark.asyncio
async def test_admin_sender_delivers_to_each_admin_and_prefers_alert_chat() -> None:
    bot = _FakeBot()
    settings = SimpleNamespace(telegram_bot_token_admin="tok", admin_telegram_ids=[1, 2, 2], ice_alert_chat_ids=None)
    assert await send_ice_health_to_admins("hi", event="t", settings=settings, bot_factory=lambda _t: bot)
    assert bot.sent == [(1, "hi"), (2, "hi")]
    bot.session.close.assert_awaited()

    bot2 = _FakeBot()
    settings2 = SimpleNamespace(telegram_bot_token_admin="tok", admin_telegram_ids=[1], ice_alert_chat_ids=[-100500])
    await send_ice_health_to_admins("hi", event="t", settings=settings2, bot_factory=lambda _t: bot2)
    assert bot2.sent == [(-100500, "hi")]


@pytest.mark.asyncio
async def test_admin_sender_without_bot_only_logs(caplog) -> None:
    factory_calls: list[str] = []

    def factory(token: str):
        factory_calls.append(token)
        return _FakeBot()

    settings = SimpleNamespace(telegram_bot_token_admin=None, admin_telegram_ids=[1], ice_alert_chat_ids=None)
    with caplog.at_level(logging.WARNING, logger="src.ingestion.alerts"):
        sent = await send_ice_health_to_admins("🔴 Лёд: тест", event="ice source alert", settings=settings, bot_factory=factory)
    assert sent is False
    assert factory_calls == []
    assert "🔴 Лёд: тест" in caplog.text
