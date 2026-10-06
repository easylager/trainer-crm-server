"""Окно публикации сеансов парсера (TASK-187).

Раньше окно замены = [min, max] дат текущей выдачи. Отменённый последний сеанс
сегодня (остальные уже прошли) и снятая вторая неделя оставались на витрине.

Теперь:
* **окно показа** — ``[сегодня по часовому поясу арены, сегодня + horizon_days)``;
  черновики вне окна отбрасываются ещё до вставки (``clip_to_publish_window``) —
  источник с месячным постом не может вставить строку поверх ещё живой старой;
* **окно удаления** — все будущие строки парсера арены начиная с сегодня
  (``ends_at_utc > now``), без верхней границы: сократившийся горизонт удаляет
  дни за новым горизонтом.

Ручные (``admin``) и эталонные (``etalon_*``) строки не трогаются никогда.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.application.ice_session_use_cases import DEFAULT_ARENA_TZ, resolve_arena_timezone
from src.ingestion.types import CanonicalSlotDraft

logger = logging.getLogger(__name__)

DEFAULT_HORIZON_DAYS = 14
MAX_HORIZON_DAYS = 62


def publish_horizon_days(config: Mapping[str, Any] | None) -> int:
    """``horizon_days`` из конфига job (тот же ключ, которым адаптеры-проекции считают дни)."""
    raw = (config or {}).get("horizon_days")
    if raw is None or isinstance(raw, bool) or raw == "":
        return DEFAULT_HORIZON_DAYS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("bad horizon_days=%r in job config; using default", raw)
        return DEFAULT_HORIZON_DAYS
    if not math.isfinite(value):
        return DEFAULT_HORIZON_DAYS
    return int(min(MAX_HORIZON_DAYS, max(1, int(value))))


def publish_timezone(config: Mapping[str, Any] | None) -> str:
    return str((config or {}).get("timezone") or "").strip() or DEFAULT_ARENA_TZ


@dataclass(frozen=True)
class PublishWindow:
    now: datetime
    today: date
    end_exclusive: date

    def contains(self, draft: CanonicalSlotDraft) -> bool:
        return self.today <= draft.local_date < self.end_exclusive and draft.ends_at_utc > self.now


def publish_window(*, now: datetime, timezone_name: str | None, horizon_days: int | None) -> PublishWindow:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        tz = resolve_arena_timezone(timezone_name)
    except Exception:  # noqa: BLE001 — кривой tz в конфиге не должен ронять публикацию
        tz = ZoneInfo(DEFAULT_ARENA_TZ)
    today = now.astimezone(tz).date()
    horizon = int(horizon_days or DEFAULT_HORIZON_DAYS)
    horizon = min(MAX_HORIZON_DAYS, max(1, horizon))
    return PublishWindow(now=now, today=today, end_exclusive=today + timedelta(days=horizon))


def publish_local_date_window(
    *,
    now: datetime,
    timezone_name: str | None,
    horizon_days: int | None,
) -> tuple[date, date]:
    """Включительные границы окна показа: ``(сегодня, сегодня + horizon - 1)``."""
    window = publish_window(now=now, timezone_name=timezone_name, horizon_days=horizon_days)
    return window.today, window.end_exclusive - timedelta(days=1)


def clip_to_publish_window(
    drafts: Sequence[CanonicalSlotDraft], window: PublishWindow
) -> tuple[list[CanonicalSlotDraft], int]:
    """(в окне, сколько отброшено за окном)."""
    kept = [d for d in drafts if window.contains(d)]
    return kept, len(drafts) - len(kept)
