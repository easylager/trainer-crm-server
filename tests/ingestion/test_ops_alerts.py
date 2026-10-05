"""TASK-178 п.3: суточный/недельный дедуп алертов льда — в БД, тики алертов — под локом."""
from __future__ import annotations

import importlib
import inspect
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.ingestion import health
from src.ingestion.health import IceHealthSnapshot, SilentJob
from src.ingestion.ops_alerts import (
    KEY_SILENT_SOURCES_DAILY,
    KEY_WEEKLY_DIGEST,
    try_alert_tick_lock,
)

# 13:00 по Минску, воскресенье.
_NOW = datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)


class _Sender:
    def __init__(self, result: bool | None = True) -> None:
        self.result = result
        self.bodies: list[str] = []

    async def __call__(self, body: str, *, event: str) -> bool | None:
        self.bodies.append(body)
        return self.result


def _silent_job() -> SilentJob:
    return SilentJob(
        job_id=1,
        arena_id=1,
        arena_name="Каток Тишина",
        city_id=1,
        city_name="Город",
        cadence="weekly",
        last_ok_at=None,
        last_status="empty",
        threshold=timedelta(days=14),
        success_rate_7d=0.0,
        success_rate_30d=0.0,
    )


@pytest.fixture
def _silent_sources(monkeypatch):
    async def detect(_session, *, now):
        return [_silent_job()]

    async def stale(_session, *, now):
        return []

    monkeypatch.setattr(health, "detect_silent_jobs", detect)
    monkeypatch.setattr(health, "stale_session_share_by_city", stale)


async def _clear_keys(db_session) -> None:
    await db_session.execute(
        text("DELETE FROM ice_ops_alerts WHERE key IN (:a, :b)"),
        {"a": KEY_SILENT_SOURCES_DAILY, "b": KEY_WEEKLY_DIGEST},
    )


def _restart_alerts_module():
    """«Рестарт сервиса»: модуль перечитан, всё, что жило в памяти процесса, потеряно."""
    from src.ingestion import alerts

    return importlib.reload(alerts)


@pytest.mark.asyncio
async def test_daily_silent_alert_is_not_duplicated_after_restart(db_session, _silent_sources) -> None:
    """AC-3: рестарт сервиса не дублирует суточный алерт."""
    await _clear_keys(db_session)
    sender = _Sender()
    alerts = _restart_alerts_module()

    body = await alerts.tick_ice_health_alerts(db_session, now=_NOW, sender=sender)
    assert body is not None and "Каток Тишина" in body

    alerts = _restart_alerts_module()
    assert await alerts.tick_ice_health_alerts(db_session, now=_NOW + timedelta(hours=1), sender=sender) is None
    # 23:30 по Минску — всё ещё тот же день.
    late = _NOW + timedelta(hours=10, minutes=30)
    assert await alerts.tick_ice_health_alerts(db_session, now=late, sender=sender) is None
    assert len(sender.bodies) == 1

    # Следующие сутки по Минску (00:30) — снова одно сообщение.
    next_day = _NOW + timedelta(hours=11, minutes=30)
    assert await alerts.tick_ice_health_alerts(db_session, now=next_day, sender=sender) is not None
    assert len(sender.bodies) == 2


@pytest.mark.asyncio
async def test_undelivered_daily_alert_is_retried(db_session, _silent_sources) -> None:
    await _clear_keys(db_session)
    from src.ingestion import alerts

    failing = _Sender(result=False)
    assert await alerts.tick_ice_health_alerts(db_session, now=_NOW, sender=failing) is None
    ok = _Sender()
    assert await alerts.tick_ice_health_alerts(db_session, now=_NOW + timedelta(hours=1), sender=ok) is not None
    assert len(failing.bodies) == 1 and len(ok.bodies) == 1


@pytest.mark.asyncio
async def test_weekly_digest_is_not_duplicated_after_restart(db_session, monkeypatch) -> None:
    await _clear_keys(db_session)

    async def snapshot(_session, *, now):
        return IceHealthSnapshot(
            silent_jobs=[],
            stale_by_city=[],
            tier_by_city=[],
            density_by_city=[],
            manual_admin_sessions_7d=0,
            calibration={"overall": None},
        )

    monkeypatch.setattr(health, "ice_health_snapshot", snapshot)
    sender = _Sender()
    for _ in range(2):
        alerts = _restart_alerts_module()

        async def no_calibration():
            return None

        monkeypatch.setattr(alerts, "_calibration_for_digest", no_calibration)
        await alerts.tick_ice_health_weekly_digest(db_session, now=_NOW, sender=sender)
    assert len(sender.bodies) == 1


@pytest.mark.asyncio
async def test_alert_tick_lock_excludes_a_second_replica(_test_db_core) -> None:
    """Две реплики: пока первая в тике (транзакция открыта), вторая тик пропускает."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.shared.config import Settings

    engine = create_async_engine(Settings().database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            assert await try_alert_tick_lock(first, "ice_source_alert") is True
            assert await try_alert_tick_lock(second, "ice_source_alert") is False
            # Другой цикл — другой лок.
            assert await try_alert_tick_lock(second, "ice_health_alert") is True
            await second.rollback()
            await first.commit()  # конец тика первой реплики — лок снят
            assert await try_alert_tick_lock(second, "ice_source_alert") is True
            await second.rollback()
    finally:
        await engine.dispose()


def test_every_alert_loop_takes_the_tick_lock() -> None:
    from src.ingestion import loop

    for fn, name in (
        (loop.run_ice_source_alert_loop, "ice_source_alert"),
        (loop.run_ice_health_alert_loop, "ice_health_alert"),
        (loop.run_ice_health_weekly_digest_loop, "ice_health_weekly_digest"),
        (loop.run_ice_scheduler_watchdog_loop, "ice_scheduler_watchdog"),
    ):
        source = inspect.getsource(fn)
        assert f'try_alert_tick_lock(session, "{name}")' in source, fn.__name__
