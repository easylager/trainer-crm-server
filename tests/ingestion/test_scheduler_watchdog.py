"""TASK-176 AC-5: сторож «нет прогонов > 2 ч при просроченных заданиях» → 🔴, восстановление → ✅."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.ingestion.scheduler_watchdog import WATCHDOG_KEY, tick_scheduler_watchdog

_T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class _Sender:
    def __init__(self, result: bool | None = True) -> None:
        self.result = result
        self.messages: list[str] = []

    async def __call__(self, body: str, *, event: str) -> bool | None:
        assert event == "ice scheduler watchdog"
        self.messages.append(body)
        return self.result


async def _isolate(db_session) -> tuple[int, int]:
    """Чистая картина внутри тестовой транзакции: только наши задание и прогоны."""
    await db_session.execute(text("UPDATE ice_parser_jobs SET is_enabled = false"))
    await db_session.execute(text("DELETE FROM ice_scrape_runs"))
    await db_session.execute(text("DELETE FROM ice_ops_alerts"))
    city = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                "VALUES ('WatchdogCity', 'BY', 'BY_BASE', true, 9310) RETURNING id"
            )
        )
    ).scalar_one()
    arena_id = int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO arenas (city_id, name, address, is_active, is_confirmed) "
                    "VALUES (:cid, 'Каток Сторож', 'ул. 1', true, true) RETURNING id"
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
                    INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, 'watchdog_test_v1', true, 'hourly', :next, '{}'::jsonb)
                    RETURNING id
                    """
                ),
                {"aid": arena_id, "next": _T0 + timedelta(days=1)},
            )
        ).scalar_one()
    )
    return arena_id, job_id


async def _set_next_run(db_session, job_id: int, at: datetime) -> None:
    await db_session.execute(
        text("UPDATE ice_parser_jobs SET next_run_at = :at WHERE id = :id"), {"at": at, "id": job_id}
    )


async def _add_run(db_session, arena_id: int, job_id: int, finished: datetime) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ice_scrape_runs (job_id, arena_id, started_at, finished_at, status)
            VALUES (:jid, :aid, :at, :at, 'ok')
            """
        ),
        {"jid": job_id, "aid": arena_id, "at": finished},
    )


async def _state(db_session) -> str | None:
    return (
        await db_session.execute(
            text("SELECT state FROM ice_ops_alerts WHERE key = :key"), {"key": WATCHDOG_KEY}
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_stalled_once_then_recovered_once(db_session) -> None:
    arena_id, job_id = await _isolate(db_session)
    await _add_run(db_session, arena_id, job_id, _T0 - timedelta(hours=3))
    await _set_next_run(db_session, job_id, _T0 - timedelta(hours=2))
    sender = _Sender()

    assert await tick_scheduler_watchdog(db_session, now=_T0, sender=sender) == "stalled"
    assert len(sender.messages) == 1 and "🔴" in sender.messages[0]
    assert "Просрочено включённых заданий: 1" in sender.messages[0]
    assert await _state(db_session) == "failing"

    # Дедуп в БД: следующий тик (в т.ч. после рестарта воркера) молчит.
    assert await tick_scheduler_watchdog(db_session, now=_T0 + timedelta(minutes=5), sender=sender) is None
    assert len(sender.messages) == 1

    # Планировщик ожил: появился прогон новее алерта.
    await _add_run(db_session, arena_id, job_id, _T0 + timedelta(minutes=10))
    await _set_next_run(db_session, job_id, _T0 + timedelta(minutes=55))
    assert await tick_scheduler_watchdog(db_session, now=_T0 + timedelta(minutes=15), sender=sender) == "recovered"
    assert len(sender.messages) == 2 and "✅" in sender.messages[1]
    assert await _state(db_session) == "ok"

    assert await tick_scheduler_watchdog(db_session, now=_T0 + timedelta(minutes=20), sender=sender) is None
    assert len(sender.messages) == 2


@pytest.mark.asyncio
async def test_no_alert_while_runs_are_fresh(db_session) -> None:
    arena_id, job_id = await _isolate(db_session)
    await _add_run(db_session, arena_id, job_id, _T0 - timedelta(hours=1, minutes=59))
    await _set_next_run(db_session, job_id, _T0 - timedelta(hours=1))
    sender = _Sender()

    assert await tick_scheduler_watchdog(db_session, now=_T0, sender=sender) is None
    assert sender.messages == []


@pytest.mark.asyncio
async def test_no_alert_at_night_when_nothing_is_due(db_session) -> None:
    arena_id, job_id = await _isolate(db_session)
    await _add_run(db_session, arena_id, job_id, _T0 - timedelta(hours=6))
    await _set_next_run(db_session, job_id, _T0 + timedelta(hours=1))
    sender = _Sender()

    assert await tick_scheduler_watchdog(db_session, now=_T0, sender=sender) is None
    # Только что ставшее due задание — ещё не повод: живой планировщик берёт его за минуту.
    await _set_next_run(db_session, job_id, _T0 - timedelta(minutes=5))
    assert await tick_scheduler_watchdog(db_session, now=_T0, sender=sender) is None
    assert sender.messages == []


@pytest.mark.asyncio
async def test_never_ran_with_overdue_jobs_is_stalled(db_session) -> None:
    _arena_id, job_id = await _isolate(db_session)
    await _set_next_run(db_session, job_id, _T0 - timedelta(hours=1))
    sender = _Sender()

    assert await tick_scheduler_watchdog(db_session, now=_T0, sender=sender) == "stalled"
    assert "ни разу" in sender.messages[0]


@pytest.mark.asyncio
async def test_undelivered_alert_is_retried_next_tick(db_session) -> None:
    arena_id, job_id = await _isolate(db_session)
    await _add_run(db_session, arena_id, job_id, _T0 - timedelta(hours=3))
    await _set_next_run(db_session, job_id, _T0 - timedelta(hours=2))
    sender = _Sender(result=False)

    assert await tick_scheduler_watchdog(db_session, now=_T0, sender=sender) is None
    assert await _state(db_session) is None

    sender.result = True
    assert await tick_scheduler_watchdog(db_session, now=_T0 + timedelta(minutes=5), sender=sender) == "stalled"
    assert len(sender.messages) == 2
    assert await _state(db_session) == "failing"
