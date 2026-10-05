"""Сторож планировщика льда (TASK-176): «прогонов нет вообще» → 🔴 в админ-бот.

Пер-источниковые алерты (source_alerts) смотрят на каждую арену отдельно и ждут 2× каденс;
ситуацию «планировщик мёртв целиком» они не называют. Сторож смотрит только на факт:
нет ни одного завершённого ``ice_scrape_runs`` дольше ``STALL_AFTER`` при том, что есть
включённые задания, просроченные дольше ``OVERDUE_GRACE``. Ночью, когда заданий к прогону
нет, тишина — норма, алерта нет.

Работает отдельным циклом в notification_service, независимо от планировщика.
Дедупликация — в ``ice_ops_alerts`` (миграция 0216):
- переход в «стоит» → один 🔴;
- появился прогон новее момента алерта → один ✅.
Недоставленный алерт (sender вернул False) состояние не двигает — повторим на следующем тике.
"""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.source_alerts import human_dt

logger = logging.getLogger(__name__)

WATCHDOG_KEY = "ice_scheduler_stalled"
STALL_AFTER = timedelta(hours=2)
# Задание, ставшее due минуту назад, ещё не повод: живой планировщик берёт его за ≤ 60 с.
OVERDUE_GRACE = timedelta(minutes=15)

STATE_OK = "ok"
STATE_FAILING = "failing"
KIND_STALLED = "stalled"
KIND_RECOVERED = "recovered"

AdminSender = Callable[..., Awaitable[bool | None]]


@dataclass(frozen=True)
class SchedulerPulse:
    last_finished_at: datetime | None
    overdue_jobs: int
    oldest_due_at: datetime | None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _hours(delta: timedelta) -> str:
    hours = max(0, int(delta.total_seconds() // 3600))
    if hours >= 48:
        return f"{hours // 24} дн"
    return f"{hours} ч"


def is_stalled(pulse: SchedulerPulse, *, now: datetime) -> bool:
    if pulse.overdue_jobs <= 0:
        return False
    last = _as_utc(pulse.last_finished_at)
    return last is None or now - last >= STALL_AFTER


def format_stalled(pulse: SchedulerPulse, *, now: datetime) -> str:
    last = _as_utc(pulse.last_finished_at)
    since = f"{human_dt(last)} ({_hours(now - last)} назад)" if last else "ни разу"
    return "\n".join(
        [
            "<b>🔴 Планировщик льда стоит</b>",
            f"Последний прогон парсеров: {html.escape(since)}.",
            f"Просрочено включённых заданий: {pulse.overdue_jobs}"
            f" (самое старое ждёт с {html.escape(human_dt(pulse.oldest_due_at))}).",
            "Расписания на витрине стареют. Проверьте сервис ice-platform-notification: "
            "в логах должна быть строка «ice ingest tick» раз в минуту.",
        ]
    )


def format_recovered(pulse: SchedulerPulse) -> str:
    return "\n".join(
        [
            "<b>✅ Планировщик льда снова работает</b>",
            f"Последний прогон: {html.escape(human_dt(pulse.last_finished_at))}.",
        ]
    )


async def load_pulse(session: AsyncSession, *, now: datetime) -> SchedulerPulse:
    row = (
        await session.execute(
            text(
                """
                SELECT
                    (SELECT MAX(finished_at) FROM ice_scrape_runs) AS last_finished_at,
                    (SELECT COUNT(*)::int FROM ice_parser_jobs
                      WHERE is_enabled = true AND next_run_at <= :overdue_before) AS overdue_jobs,
                    (SELECT MIN(next_run_at) FROM ice_parser_jobs
                      WHERE is_enabled = true AND next_run_at <= :overdue_before) AS oldest_due_at
                """
            ),
            {"overdue_before": now - OVERDUE_GRACE},
        )
    ).one()
    return SchedulerPulse(
        last_finished_at=_as_utc(row.last_finished_at),
        overdue_jobs=int(row.overdue_jobs or 0),
        oldest_due_at=_as_utc(row.oldest_due_at),
    )


async def _load_state(session: AsyncSession) -> tuple[str, datetime | None]:
    row = (
        await session.execute(
            text("SELECT state, changed_at FROM ice_ops_alerts WHERE key = :key"),
            {"key": WATCHDOG_KEY},
        )
    ).first()
    if row is None:
        return STATE_OK, None
    return str(row.state or STATE_OK), _as_utc(row.changed_at)


async def _save_state(session: AsyncSession, *, state: str, now: datetime) -> None:
    await session.execute(
        text(
            """
            INSERT INTO ice_ops_alerts (key, state, changed_at, sent_at)
            VALUES (:key, :state, :now, :now)
            ON CONFLICT (key) DO UPDATE
            SET state = EXCLUDED.state, changed_at = EXCLUDED.changed_at, sent_at = EXCLUDED.sent_at
            """
        ),
        {"key": WATCHDOG_KEY, "state": state, "now": now},
    )


async def tick_scheduler_watchdog(
    session: AsyncSession,
    *,
    now: datetime,
    sender: AdminSender | None = None,
) -> str | None:
    """Один тик сторожа. Возвращает ``stalled`` / ``recovered`` или None. Коммитит вызывающий."""
    now = _as_utc(now) or now
    pulse = await load_pulse(session, now=now)
    state, changed_at = await _load_state(session)

    if state != STATE_FAILING and is_stalled(pulse, now=now):
        kind, body, new_state = KIND_STALLED, format_stalled(pulse, now=now), STATE_FAILING
    elif (
        state == STATE_FAILING
        and pulse.last_finished_at is not None
        and (changed_at is None or pulse.last_finished_at > changed_at)
    ):
        kind, body, new_state = KIND_RECOVERED, format_recovered(pulse), STATE_OK
    else:
        return None

    if sender is None:
        from src.ingestion.alerts import send_ice_health_to_admins

        sender = send_ice_health_to_admins
    delivered = await sender(body, event="ice scheduler watchdog")
    if delivered is False:
        logger.warning("ice scheduler watchdog: %s alert not delivered; will retry", kind)
        return None
    await _save_state(session, state=new_state, now=now)
    logger.warning(
        "ice scheduler watchdog: %s (last run %s, overdue jobs %s)",
        kind,
        pulse.last_finished_at,
        pulse.overdue_jobs,
    )
    return kind


__all__ = [
    "OVERDUE_GRACE",
    "STALL_AFTER",
    "WATCHDOG_KEY",
    "SchedulerPulse",
    "format_recovered",
    "format_stalled",
    "is_stalled",
    "load_pulse",
    "tick_scheduler_watchdog",
]
