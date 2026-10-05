"""Publish window for parser-owned ice_sessions (TASK-187)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.application.ice_session_use_cases import DEFAULT_ARENA_TZ

DEFAULT_HORIZON_DAYS = 14


def publish_local_date_window(
    *,
    now: datetime,
    timezone_name: str | None,
    horizon_days: int | None,
) -> tuple[date, date]:
    tz = ZoneInfo((timezone_name or "").strip() or DEFAULT_ARENA_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    today = now.astimezone(tz).date()
    horizon = int(horizon_days or DEFAULT_HORIZON_DAYS)
    if horizon < 1:
        horizon = 1
    hi = today + timedelta(days=horizon - 1)
    return today, hi
