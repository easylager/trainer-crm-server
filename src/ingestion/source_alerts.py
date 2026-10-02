"""Пуш в админ-бот, когда парсер конкретной арены сломался или расписание устарело (TASK-146).

Цель — админ сразу видит, где мы вводим пользователей в заблуждение. Поэтому алерт
говорит не только «что упало», но и «что сейчас видят люди».

Дедупликация живёт на ice_parser_jobs (alert_state / alert_sent_at, миграция 0211),
а не в памяти процесса — рестарт воркера не даёт ни повторного залпа, ни потери
«восстановлено»:
- переход в сбой → один алерт 🔴;
- сбой продолжается → напоминание 🟠 не чаще ``REMINDER_EVERY`` и только днём;
- сбой закончился → одно «✅ восстановлено».
Несколько арен в одном тике уходят одним сообщением (порезанным по лимиту Telegram).

Без настроенного админ-бота текст пишется в лог, состояние двигается как обычно.
"""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.freshness import (
    CONFIG_ALERTS_MUTED,
    ERROR_CODE_EMPTY_AFTER_SLOTS,
    MINSK_TZ,
    config_flag,
    is_schedule_stale,
    stale_after,
)
from src.ingestion.types import ALERT_STATE_FAILING, ALERT_STATE_OK

logger = logging.getLogger(__name__)

# Один упавший прогон — чаще всего сетевой сбой, и через 15 минут повтор проходит.
# Алертим со второго подряд: это ~15 минут от первого сбоя.
ALERT_AFTER_FAILURES = 2
REMINDER_EVERY = timedelta(hours=4)
# Напоминания — только днём по Минску; первый алерт и «восстановлено» — в любое время.
REMINDER_DAY_START_HOUR = 9
REMINDER_DAY_END_HOUR = 22
TELEGRAM_CHUNK_LIMIT = 3800

KIND_FAILING = "failing"
KIND_REMINDER = "reminder"
KIND_RECOVERED = "recovered"

_ERROR_LABELS = {
    "extract_error": "парсер упал при чтении сайта",
    "validation_error": "данные с сайта не прошли проверку",
    "publish_error": "не удалось записать сеансы в базу",
    "unknown_parser_key": "в коде нет парсера с таким ключом",
    "requires_by_egress": "нужен выход в сеть из BY, на воркере его нет",
    ERROR_CODE_EMPTY_AFTER_SLOTS: "источник вернул 0 сеансов",
    "blocked": "источник заблокирован",
    "error": "ошибка прогона",
}

_MONTHS_SHORT_RU = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")

AdminSender = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class SourceHealthRow:
    job_id: int
    arena_id: int
    arena_name: str
    city_name: str
    parser_key: str
    is_enabled: bool
    config: dict[str, Any]
    created_at: datetime | None
    last_run_at: datetime | None
    last_ok_at: datetime | None
    last_ok_slot_count: int | None
    failing_since: datetime | None
    failure_streak: int
    last_error_code: str | None
    last_error_summary: str | None
    alert_state: str
    alert_sent_at: datetime | None
    shown_sessions: int
    shown_observed_at: datetime | None


@dataclass(frozen=True)
class SourceAlert:
    job_id: int
    kind: str
    text: str


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def human_dt(value: datetime | None) -> str:
    """«1 окт, 14:00» по Минску — так, как админ читает это в телефоне."""
    value = _as_utc(value)
    if value is None:
        return "никогда"
    local = value.astimezone(MINSK_TZ)
    return f"{local.day} {_MONTHS_SHORT_RU[local.month - 1]}, {local:%H:%M}"


def _human_span(delta: timedelta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    hours, mins = divmod(minutes, 60)
    if hours >= 48:
        return f"{hours // 24} дн"
    if hours:
        return f"{hours} ч {mins} мин" if mins else f"{hours} ч"
    return f"{mins} мин"


def _sessions_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "сеанс"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "сеанса"
    return "сеансов"


def _is_stale(row: SourceHealthRow, now: datetime) -> bool:
    return is_schedule_stale(
        has_enabled_job=row.is_enabled,
        last_ok_at=row.last_ok_at,
        config=row.config,
        now=now,
        created_at=row.created_at,
    )


def is_alerting(row: SourceHealthRow, now: datetime) -> bool:
    """Должен ли источник сейчас считаться «сломанным» для админа."""
    if not row.is_enabled or config_flag(row.config, CONFIG_ALERTS_MUTED):
        return False
    if row.failure_streak >= ALERT_AFTER_FAILURES:
        return True
    # Ошибок нет, а расписание давно не подтверждалось при непустой витрине —
    # например, планировщик не доходит до источника. Пользователь видит старое.
    return row.shown_sessions > 0 and _is_stale(row, now)


def _what_failed(row: SourceHealthRow, now: datetime) -> str:
    if row.failure_streak >= ALERT_AFTER_FAILURES or row.last_error_code:
        code = row.last_error_code or "error"
        label = _ERROR_LABELS.get(code, code)
        summary = (row.last_error_summary or "").strip()
        if summary and code != ERROR_CODE_EMPTY_AFTER_SLOTS:
            summary = summary.splitlines()[0][:160]
            return f"{html.escape(label)} — <code>{html.escape(summary)}</code>"
        if summary:
            return html.escape(summary)
        return html.escape(label)
    limit = stale_after(row.config)
    return html.escape(
        f"расписание не подтверждалось дольше {_human_span(limit)}, хотя ошибок нет "
        "(планировщик не доходит до источника?)"
    )


def _since_line(row: SourceHealthRow, now: datetime) -> str:
    if row.failing_since is not None:
        attempts = row.failure_streak
        return (
            f"С: {human_dt(row.failing_since)} "
            f"({_human_span(now - _as_utc(row.failing_since))}, попыток подряд: {attempts})"
        )
    return f"Последний успешный прогон: {human_dt(row.last_ok_at)}"


def what_users_see(row: SourceHealthRow) -> str:
    if row.shown_sessions <= 0:
        return "расписания нет — карточка без сеансов"
    observed = row.shown_observed_at or row.last_ok_at
    n = row.shown_sessions
    return f"расписание от {human_dt(observed)} — {n} {_sessions_word(n)}"


def _title(row: SourceHealthRow) -> str:
    name = html.escape(row.arena_name or f"арена #{row.arena_id}")
    city = html.escape(row.city_name or "")
    where = f"{name} ({city})" if city else name
    return f"<b>{where}</b> · <code>{html.escape(row.parser_key)}</code>"


def format_source_alert(row: SourceHealthRow, *, kind: str, now: datetime) -> str:
    if kind == KIND_RECOVERED:
        if not row.is_enabled:
            head = "✅ Лёд: источник выключен, алерт снят"
        elif config_flag(row.config, CONFIG_ALERTS_MUTED):
            head = "✅ Лёд: алерты источника заглушены (alerts_muted)"
        else:
            head = "✅ Лёд: источник восстановлен"
        return "\n".join(
            [
                head,
                _title(row),
                f"Пользователи видят: {what_users_see(row)}",
            ]
        )
    head = "🔴 Лёд: сломался источник" if kind == KIND_FAILING else "🟠 Лёд: всё ещё не работает"
    return "\n".join(
        [
            head,
            _title(row),
            f"Что: {_what_failed(row, now)}",
            _since_line(row, now),
            f"Пользователи видят: {what_users_see(row)}",
        ]
    )


def _reminder_window(now: datetime) -> bool:
    local = now.astimezone(MINSK_TZ)
    return REMINDER_DAY_START_HOUR <= local.hour < REMINDER_DAY_END_HOUR


def decide_source_alerts(rows: list[SourceHealthRow], *, now: datetime) -> list[SourceAlert]:
    """Чистое решение: кому что отправить на этом тике. Без БД и Telegram."""
    now = _as_utc(now) or now
    alerts: list[SourceAlert] = []
    for row in rows:
        alerting = is_alerting(row, now)
        if alerting and row.alert_state != ALERT_STATE_FAILING:
            kind = KIND_FAILING
        elif alerting:
            sent = _as_utc(row.alert_sent_at)
            due = sent is None or now - sent >= REMINDER_EVERY
            if not (due and _reminder_window(now)):
                continue
            kind = KIND_REMINDER
        elif row.alert_state == ALERT_STATE_FAILING:
            kind = KIND_RECOVERED
        else:
            continue
        alerts.append(
            SourceAlert(job_id=row.job_id, kind=kind, text=format_source_alert(row, kind=kind, now=now))
        )
    return alerts


def chunk_messages(blocks: list[str], *, limit: int = TELEGRAM_CHUNK_LIMIT) -> list[str]:
    """Склеить блоки в минимум сообщений, не превышая лимит Telegram."""
    chunks: list[str] = []
    current = ""
    for block in blocks:
        block = block[:limit]
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


_ROWS_SQL = """
SELECT
    j.id AS job_id, j.arena_id, j.parser_key, j.is_enabled, j.config, j.created_at,
    j.last_run_at, j.last_ok_at, j.last_ok_slot_count, j.failing_since, j.failure_streak,
    j.last_error_code, j.last_error_summary, j.alert_state, j.alert_sent_at,
    a.name AS arena_name, c.name AS city_name,
    COALESCE(sh.shown, 0) AS shown_sessions,
    sh.observed_at AS shown_observed_at
FROM ice_parser_jobs AS j
JOIN arenas AS a ON a.id = j.arena_id
LEFT JOIN cities AS c ON c.id = a.city_id
LEFT JOIN LATERAL (
    SELECT COUNT(*)::int AS shown, MAX(s.observed_at) AS observed_at
    FROM ice_sessions AS s
    WHERE s.arena_id = j.arena_id
      AND s.status = 'active'
      AND s.kind IN ('public_skate', 'open_ice')
      AND s.starts_at_utc > :now
      AND (s.valid_until IS NULL OR s.valid_until >= :now)
      AND (s.source_id IS NULL OR s.source_id NOT LIKE 'etalon_%')
      AND (s.source_id IS NULL OR s.source_id <> 'admin')
) AS sh ON true
WHERE j.is_enabled = true OR j.alert_state = :failing
ORDER BY j.id
"""


async def load_source_health_rows(session: AsyncSession, *, now: datetime) -> list[SourceHealthRow]:
    result = await session.execute(text(_ROWS_SQL), {"now": now, "failing": ALERT_STATE_FAILING})
    rows: list[SourceHealthRow] = []
    for r in result.mappings():
        rows.append(
            SourceHealthRow(
                job_id=int(r["job_id"]),
                arena_id=int(r["arena_id"]),
                arena_name=str(r["arena_name"] or ""),
                city_name=str(r["city_name"] or ""),
                parser_key=str(r["parser_key"]),
                is_enabled=bool(r["is_enabled"]),
                config=dict(r["config"]) if isinstance(r["config"], dict) else {},
                created_at=r["created_at"],
                last_run_at=r["last_run_at"],
                last_ok_at=r["last_ok_at"],
                last_ok_slot_count=r["last_ok_slot_count"],
                failing_since=r["failing_since"],
                failure_streak=int(r["failure_streak"] or 0),
                last_error_code=r["last_error_code"],
                last_error_summary=r["last_error_summary"],
                alert_state=str(r["alert_state"] or ALERT_STATE_OK),
                alert_sent_at=r["alert_sent_at"],
                shown_sessions=int(r["shown_sessions"] or 0),
                shown_observed_at=r["shown_observed_at"],
            )
        )
    return rows


async def _apply_alert_state(session: AsyncSession, alerts: list[SourceAlert], *, now: datetime) -> None:
    for alert in alerts:
        state = ALERT_STATE_OK if alert.kind == KIND_RECOVERED else ALERT_STATE_FAILING
        await session.execute(
            text(
                """
                UPDATE ice_parser_jobs
                SET alert_state = :state, alert_sent_at = :now
                WHERE id = :job_id
                """
            ),
            {"state": state, "now": now, "job_id": alert.job_id},
        )


async def tick_source_failure_alerts(
    session: AsyncSession,
    *,
    now: datetime,
    sender: AdminSender | None = None,
) -> list[SourceAlert]:
    """Один тик: прочитать состояние источников, отправить нужное, сдвинуть alert_state.

    Коммитит вызывающий. ``sender`` — для тестов; по умолчанию админ-бот.
    """
    now = _as_utc(now) or now
    rows = await load_source_health_rows(session, now=now)
    alerts = decide_source_alerts(rows, now=now)
    if not alerts:
        return []
    if sender is None:
        from src.ingestion.alerts import send_ice_health_to_admins

        sender = send_ice_health_to_admins
    for chunk in chunk_messages([a.text for a in alerts]):
        await sender(chunk, event="ice source alert")
    await _apply_alert_state(session, alerts, now=now)
    return alerts


__all__ = [
    "ALERT_AFTER_FAILURES",
    "KIND_FAILING",
    "KIND_RECOVERED",
    "KIND_REMINDER",
    "REMINDER_EVERY",
    "SourceAlert",
    "SourceHealthRow",
    "chunk_messages",
    "decide_source_alerts",
    "format_source_alert",
    "human_dt",
    "is_alerting",
    "load_source_health_rows",
    "tick_source_failure_alerts",
    "what_users_see",
]
