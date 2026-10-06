"""Дедуп и взаимоисключение алертов льда в БД, а не в памяти процесса (TASK-178).

- ``ice_ops_alerts`` (миграция 0216, TASK-176) хранит, когда ушёл суточный / недельный
  алерт: рестарт воркера или вторая реплика не шлют его повторно.
- Тики алертов идут под транзакционным advisory-локом: две реплики не читают одно и то
  же ``alert_state`` одновременно и не шлют одинаковый пуш дважды. Лок снимается сам
  на commit/rollback сессии тика.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.freshness import MINSK_TZ

# Пространство advisory-локов алертов ("ICEA"); второй ключ — номер цикла.
ALERT_TICK_LOCK_NAMESPACE = 0x49434541
ALERT_TICK_LOCKS = {
    "ice_source_alert": 1,
    "ice_health_alert": 2,
    "ice_health_weekly_digest": 3,
    "ice_scheduler_watchdog": 4,
}

KEY_SILENT_SOURCES_DAILY = "ice_health_silent_daily"
KEY_WEEKLY_DIGEST = "ice_health_weekly_digest"


async def try_alert_tick_lock(session: AsyncSession, name: str) -> bool:
    """Взять лок тика ``name`` до конца транзакции сессии. False — тик уже идёт в другом процессе."""
    lock_id = ALERT_TICK_LOCKS[name]
    acquired = (
        await session.execute(
            text("SELECT pg_try_advisory_xact_lock(:ns, :id)"),
            {"ns": ALERT_TICK_LOCK_NAMESPACE, "id": lock_id},
        )
    ).scalar_one()
    return bool(acquired)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def minsk_date(value: datetime) -> date:
    return (_as_utc(value) or value).astimezone(MINSK_TZ).date()


async def ops_alert_sent_at(session: AsyncSession, key: str) -> datetime | None:
    """Когда алерт ``key`` ушёл в последний раз (строка блокируется до конца транзакции)."""
    row = (
        await session.execute(
            text("SELECT sent_at FROM ice_ops_alerts WHERE key = :key FOR UPDATE"),
            {"key": key},
        )
    ).first()
    return _as_utc(row.sent_at) if row is not None else None


async def mark_ops_alert_sent(session: AsyncSession, key: str, *, now: datetime) -> None:
    await session.execute(
        text(
            """
            INSERT INTO ice_ops_alerts (key, state, changed_at, sent_at)
            VALUES (:key, 'ok', :now, :now)
            ON CONFLICT (key) DO UPDATE SET sent_at = EXCLUDED.sent_at
            """
        ),
        {"key": key, "now": now},
    )


async def sent_today_minsk(session: AsyncSession, key: str, *, now: datetime) -> bool:
    sent = await ops_alert_sent_at(session, key)
    return sent is not None and minsk_date(sent) == minsk_date(now)


__all__ = [
    "ALERT_TICK_LOCKS",
    "ALERT_TICK_LOCK_NAMESPACE",
    "KEY_SILENT_SOURCES_DAILY",
    "KEY_WEEKLY_DIGEST",
    "mark_ops_alert_sent",
    "minsk_date",
    "ops_alert_sent_at",
    "sent_today_minsk",
    "try_alert_tick_lock",
]
