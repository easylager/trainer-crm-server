"""Filter matching for client ice watches (mirrors ice list window semantics)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from src.application.ice_time_windows import resolve_list_window


def filter_label(filter_json: Mapping[str, Any] | None) -> str:
    fj = dict(filter_json or {})
    when = (fj.get("when") or "any").strip().lower()
    day = (fj.get("day") or "").strip() or None
    parts: list[str] = ["Массовый каток"]
    if day:
        parts.append(day)
    elif when == "weekend":
        parts.append("выходные")
    elif when == "today_evening":
        parts.append("сегодня вечером")
    elif when == "today":
        parts.append("сегодня")
    elif when == "tomorrow":
        parts.append("завтра")
    elif when not in ("", "any"):
        parts.append(when)
    return " · ".join(parts)


def session_matches_filter(
    session_row: Mapping[str, Any],
    filter_json: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    fj = dict(filter_json or {})
    when = fj.get("when")
    day = fj.get("day")
    window = resolve_list_window(when, day, now)
    if window is None:
        return True
    starts = session_row.get("starts_at_utc")
    if starts is None:
        return False
    if isinstance(starts, str):
        starts = datetime.fromisoformat(starts.replace("Z", "+00:00"))
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=timezone.utc)
    return window.starts_at <= starts < window.ends_at
