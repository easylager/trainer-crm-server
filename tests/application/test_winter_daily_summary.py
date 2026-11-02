"""Ежедневная сводка «Зимой» в админ-бот: 10:00 по Минску, без дублей, повтор при сбое доставки."""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from src.application.winter_report import tick_winter_daily_summary

# 10:30 по Минску (UTC+3) = 07:30 UTC; 09:30 по Минску = 06:30 UTC
_AFTER = datetime(2026, 11, 20, 7, 30, tzinfo=timezone.utc)
_BEFORE = datetime(2026, 11, 20, 6, 30, tzinfo=timezone.utc)
_NEXT_DAY = datetime(2026, 11, 21, 7, 30, tzinfo=timezone.utc)


class _Sender:
    def __init__(self, result: bool | None = True) -> None:
        self.result = result
        self.bodies: list[str] = []

    async def __call__(self, body: str, *, event: str) -> bool | None:
        self.bodies.append(body)
        return self.result


async def _clear(session) -> None:
    await session.execute(text("DELETE FROM ice_ops_alerts WHERE key = 'winter_daily_summary'"))


@pytest.mark.asyncio
async def test_not_sent_before_ten_minsk(db_session) -> None:
    await _clear(db_session)
    sender = _Sender()
    assert await tick_winter_daily_summary(db_session, _BEFORE, sender=sender) is None
    assert sender.bodies == []


@pytest.mark.asyncio
async def test_sent_once_a_day_and_again_next_day(db_session) -> None:
    await _clear(db_session)
    sender = _Sender()
    first = await tick_winter_daily_summary(db_session, _AFTER, sender=sender)
    assert first is not None and first.startswith("Зимой:")
    # «рестарт»: тот же день, новая сессия/тик — дубля нет
    assert await tick_winter_daily_summary(db_session, _AFTER, sender=sender) is None
    assert len(sender.bodies) == 1
    assert await tick_winter_daily_summary(db_session, _NEXT_DAY, sender=sender) is not None
    assert len(sender.bodies) == 2


@pytest.mark.asyncio
async def test_failed_delivery_is_retried(db_session) -> None:
    await _clear(db_session)
    failing, ok = _Sender(False), _Sender(True)
    assert await tick_winter_daily_summary(db_session, _AFTER, sender=failing) is None
    assert await tick_winter_daily_summary(db_session, _AFTER, sender=ok) is not None


def test_loop_is_flag_gated_and_takes_the_tick_lock() -> None:
    from src.bot import notification_service, winter_bot

    source = inspect.getsource(winter_bot.run_winter_summary_loop)
    assert "_enabled()" in source and 'try_alert_tick_lock(session, "winter_daily_summary")' in source
    assert "run_winter_summary_loop" in inspect.getsource(notification_service.main)
