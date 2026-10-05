"""Свежесть расписания льда: как часто опрашивать источник и когда он «устарел» (TASK-146).

Чистая логика без БД и HTTP — её используют планировщик (когда следующий прогон),
публичный API (флаг ``schedule_stale``) и алерты админ-бота (что считать сбоем).

Каденс задания (hourly/daily/weekly) раньше был единственным расписанием опроса:
weekly-источник перечитывался раз в неделю, а упавший прогон повторялся через тот же
каденс. Теперь опрос — по времени суток Минска (днём каждые ~45 минут, ночью реже)
с джиттером, бэкоффом при ошибках и ручным потолком ``poll_minutes`` на вежливость.
"""
from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.ingestion.types import (
    ALERT_STATE_FAILING,
    ALERT_STATE_OK,
    RUN_STATUS_BLOCKED,
    RUN_STATUS_EMPTY,
    RUN_STATUS_ERROR,
    RUN_STATUS_OK,
    ScrapeRunRecord,
    SourceState,
)
from src.shared.notification_hours import NOTIFICATION_TZ

MINSK_TZ = ZoneInfo(NOTIFICATION_TZ)

# Днём катки публикуют и правят расписание — опрашиваем часто. Ночью — реже, но так,
# чтобы к утру (07:00–07:30) каждый источник был перечитан заново.
DAY_START_HOUR = 7
DAY_END_HOUR = 23
DAY_POLL_MINUTES = 45
NIGHT_POLL_MINUTES = 120
MORNING_SPREAD_MINUTES = 30
JITTER_SHARE = 0.15

# Ошибка: первый повтор через 15 минут (обычно это сетевой сбой), дальше удваиваем
# до 3 часов — сломанный сайт не долбим, но починку замечаем в пределах пары часов.
FAILURE_RETRY_BASE_MINUTES = 15
FAILURE_RETRY_MAX_MINUTES = 180
# blocked — это конфигурация воркера (нет BY-egress), а не сайт; часто не повторяем.
BLOCKED_RETRY_MINUTES = 360

# Расписание считается устаревшим, если источник не читался успешно дольше порога.
# 6 часов днём — это ~8 неудачных попыток подряд, а не одна случайная.
DEFAULT_STALE_AFTER_HOURS = 6

CONFIG_POLL_MINUTES = "poll_minutes"
CONFIG_STALE_AFTER_HOURS = "stale_after_hours"
CONFIG_ALERTS_MUTED = "alerts_muted"

ERROR_CODE_EMPTY_AFTER_SLOTS = "empty_after_slots"
# TASK-178: почему прогон пустой. Источник не дал ни одного слота (вёрстка? межсезонье?)
# или дал, но все отброшены нормализацией (обычно — все сеансы уже прошли).
ERROR_CODE_EMPTY_SOURCE = "empty_source"
ERROR_CODE_EMPTY_AFTER_FILTER = "empty_after_filter"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _config_float(config: dict[str, Any] | None, key: str) -> float | None:
    raw = (config or {}).get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def config_flag(config: dict[str, Any] | None, key: str) -> bool:
    raw = (config or {}).get(key, False)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return bool(raw)


def is_run_failure(record: ScrapeRunRecord, *, shown_sessions: int) -> bool:
    """Прогон, который удлиняет серию сбоев (и даёт быстрый 🔴 со второго подряд).

    error/blocked — всегда. empty — только если у арены ещё висят будущие сеансы
    из прошлых прогонов: empty их не удаляет (защита от сломанного парсера), значит
    мы показываем то, чего источник больше не подтверждает.

    Пустой прогон при пустой витрине — не сбой, но и **не выздоровление** (TASK-178):
    серию он не обнуляет и ``last_ok_at`` не двигает. Иначе «вёрстка сломалась →
    старые сеансы истекли» давало ложное ✅. Долгую пустоту ловит порог устаревания
    в алертах (от последнего ok, независимо от витрины).
    """
    if record.status in (RUN_STATUS_ERROR, RUN_STATUS_BLOCKED):
        return True
    if record.status == RUN_STATUS_EMPTY:
        return shown_sessions > 0
    return False


def _empty_code(record: ScrapeRunRecord) -> str:
    if record.error_code in (ERROR_CODE_EMPTY_SOURCE, ERROR_CODE_EMPTY_AFTER_FILTER):
        return record.error_code
    return ERROR_CODE_EMPTY_AFTER_FILTER if record.slots_dropped > 0 else ERROR_CODE_EMPTY_SOURCE


def next_source_state(
    prev: SourceState,
    record: ScrapeRunRecord,
    *,
    shown_sessions: int,
) -> SourceState:
    """Новое состояние после прогона. Алертные поля не трогаем — их ведёт alerts.

    Серию сбоев обнуляет только ``ok`` — прогон, который реально опубликовал сеансы.
    """
    finished = _as_utc(record.finished_at)
    if record.status == RUN_STATUS_OK:
        return replace(
            prev,
            last_ok_at=finished,
            last_ok_slot_count=int(record.slot_count),
            failing_since=None,
            failure_streak=0,
            last_error_code=None,
            last_error_summary=None,
        )
    if not is_run_failure(record, shown_sessions=shown_sessions):
        # empty при пустой витрине: показывать нечего. Серию не трогаем (ни +1, ни сброс),
        # last_ok_at не двигаем, но запоминаем причину — её покажет алерт устаревания.
        return replace(
            prev,
            last_error_code=_empty_code(record),
            last_error_summary=(record.error_message or "")[:500] or None,
        )
    if record.status == RUN_STATUS_EMPTY:
        code = ERROR_CODE_EMPTY_AFTER_SLOTS
        summary = f"источник вернул 0 сеансов, а у нас показано {shown_sessions}"
        if record.error_message:
            summary = f"{summary} ({record.error_message})"
    else:
        code = record.error_code or record.status
        summary = record.error_message
    return replace(
        prev,
        failing_since=prev.failing_since or finished,
        failure_streak=prev.failure_streak + 1,
        last_error_code=(code or "")[:64] or None,
        last_error_summary=(summary or "")[:500] or None,
    )


def replay_source_state(
    runs: list[ScrapeRunRecord],
    *,
    shown_sessions: int,
    start: SourceState | None = None,
) -> SourceState:
    """Состояние источника, пересчитанное по истории прогонов (старые → новые).

    Историческое число видимых сеансов не хранится, поэтому для empty берётся
    ``shown_sessions`` — текущая витрина (то же приближение, что в backfill 0211).
    """
    state = start or SourceState()
    for record in sorted(runs, key=lambda r: _as_utc(r.finished_at)):
        state = next_source_state(state, record, shown_sessions=shown_sessions)
    return state


def _is_daytime(local: datetime) -> bool:
    return DAY_START_HOUR <= local.hour < DAY_END_HOUR


def _next_morning(local: datetime) -> datetime:
    day = local.date() if local.hour < DAY_START_HOUR else local.date() + timedelta(days=1)
    return datetime.combine(day, time(DAY_START_HOUR), tzinfo=MINSK_TZ)


def base_poll_interval(now: datetime, config: dict[str, Any] | None = None) -> timedelta:
    """Плановый интервал опроса для успешного прогона: день/ночь или ручной потолок."""
    manual = _config_float(config, CONFIG_POLL_MINUTES)
    if manual is not None:
        return timedelta(minutes=manual)
    local = _as_utc(now).astimezone(MINSK_TZ)
    minutes = DAY_POLL_MINUTES if _is_daytime(local) else NIGHT_POLL_MINUTES
    return timedelta(minutes=minutes)


def failure_retry_interval(failure_streak: int) -> timedelta:
    streak = max(1, int(failure_streak))
    minutes = FAILURE_RETRY_BASE_MINUTES * (2 ** min(streak - 1, 10))
    return timedelta(minutes=min(minutes, FAILURE_RETRY_MAX_MINUTES))


def next_poll_at(
    *,
    job_id: int,
    config: dict[str, Any] | None,
    status: str,
    state: SourceState,
    now: datetime,
    rng: random.Random | None = None,
) -> datetime:
    """Когда опросить источник снова.

    - ok / empty: день — 45 мин, ночь — 120 мин, но не позже утреннего окна
      07:00–07:30 (смещение по job_id, чтобы утром не бить все сайты разом);
    - error: 15 → 30 → 60 → 120 → 180 мин по длине серии;
    - blocked: 6 часов;
    - ``config.poll_minutes`` — ручной интервал для источника, который просит реже.
    Джиттер ±15% разносит источники по минутам, чтобы не было залпов.
    """
    now = _as_utc(now)
    rnd = rng or random
    manual = _config_float(config, CONFIG_POLL_MINUTES)
    if status == RUN_STATUS_BLOCKED:
        delay = timedelta(minutes=BLOCKED_RETRY_MINUTES)
    elif status == RUN_STATUS_ERROR:
        delay = failure_retry_interval(state.failure_streak)
        if manual is not None:
            delay = max(delay, timedelta(minutes=manual))
    else:
        delay = base_poll_interval(now, config)
    jitter = 1.0 + rnd.uniform(-JITTER_SHARE, JITTER_SHARE)
    candidate = now + delay * jitter
    if manual is not None:
        candidate = max(candidate, now + timedelta(minutes=manual))
    if manual is None and status in (RUN_STATUS_OK, RUN_STATUS_EMPTY):
        local_now = now.astimezone(MINSK_TZ)
        if not _is_daytime(local_now):
            morning = _next_morning(local_now) + timedelta(
                minutes=job_id % MORNING_SPREAD_MINUTES
            )
            morning_utc = morning.astimezone(timezone.utc)
            if candidate > morning_utc:
                candidate = morning_utc
    return candidate


def stale_after(config: dict[str, Any] | None) -> timedelta:
    hours = _config_float(config, CONFIG_STALE_AFTER_HOURS)
    return timedelta(hours=hours if hours is not None else DEFAULT_STALE_AFTER_HOURS)


def is_schedule_stale(
    *,
    has_enabled_job: bool,
    last_ok_at: datetime | None,
    config: dict[str, Any] | None,
    now: datetime,
    created_at: datetime | None = None,
    sessions_observed_at: datetime | None = None,
) -> bool:
    """Расписание арены устарело: есть автоматический источник, но он давно не читался.

    Без включённого парсера (ручной ввод, etalon) флаг всегда False — там нечему
    «устаревать» автоматически. Новый источник, ещё ни разу не прочитанный, получает
    тот же порог от момента создания, а не «устаревший» сразу.

    ``sessions_observed_at`` — свежие сеансы в БД (тот же смысл, что в
    ``schedule_observed_at``): если они новее ``last_ok_at``, порог считаем от них.
    """
    if not has_enabled_job:
        return False
    anchor = last_ok_at or created_at
    if sessions_observed_at is not None:
        s = _as_utc(sessions_observed_at)
        if anchor is None or s > _as_utc(anchor):
            anchor = sessions_observed_at
    if anchor is None:
        return True
    return _as_utc(now) - _as_utc(anchor) > stale_after(config)


def schedule_freshness_fields(
    *,
    has_enabled_job: bool,
    last_ok_at: datetime | None,
    sessions_observed_at: datetime | None,
    config: dict[str, Any] | None,
    now: datetime,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Поля ``freshness`` для публичного API (карточка, лента, сеансы арены).

    ``schedule_observed_at`` — когда расписание последний раз подтверждено: последний
    успешный прогон парсера, а без парсера — самое свежее observed_at показанных сеансов.
    """
    candidates = [_as_utc(v) for v in (last_ok_at, sessions_observed_at) if v is not None]
    observed = max(candidates) if candidates else None
    stale = is_schedule_stale(
        has_enabled_job=has_enabled_job,
        last_ok_at=last_ok_at,
        sessions_observed_at=sessions_observed_at,
        config=config,
        now=now,
        created_at=created_at,
    )
    return {
        "schedule_observed_at": observed.isoformat() if observed else None,
        "schedule_auto": bool(has_enabled_job),
        "schedule_stale": stale,
    }


__all__ = [
    "ALERT_STATE_FAILING",
    "ALERT_STATE_OK",
    "BLOCKED_RETRY_MINUTES",
    "CONFIG_ALERTS_MUTED",
    "CONFIG_POLL_MINUTES",
    "CONFIG_STALE_AFTER_HOURS",
    "DAY_POLL_MINUTES",
    "DEFAULT_STALE_AFTER_HOURS",
    "ERROR_CODE_EMPTY_AFTER_FILTER",
    "ERROR_CODE_EMPTY_AFTER_SLOTS",
    "ERROR_CODE_EMPTY_SOURCE",
    "MINSK_TZ",
    "NIGHT_POLL_MINUTES",
    "SourceState",
    "base_poll_interval",
    "config_flag",
    "failure_retry_interval",
    "is_run_failure",
    "is_schedule_stale",
    "next_poll_at",
    "next_source_state",
    "replay_source_state",
    "schedule_freshness_fields",
    "stale_after",
]
