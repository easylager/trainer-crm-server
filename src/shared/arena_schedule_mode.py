"""Режим расписания арены (TASK-204): auto | phone | season_closed.

Пара с ``static/webapp/arena-schedule-mode-model.js`` — тексты для пользователя держать в паре.
Не путать с устареванием (TASK-180) и основанием сеанса (TASK-179).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

SCHEDULE_MODE_AUTO = "auto"
SCHEDULE_MODE_PHONE = "phone"
SCHEDULE_MODE_SEASON_CLOSED = "season_closed"

SCHEDULE_MODES = (
    SCHEDULE_MODE_AUTO,
    SCHEDULE_MODE_PHONE,
    SCHEDULE_MODE_SEASON_CLOSED,
)

PHONE_LINE = "Расписание по телефону"
SEASON_CLOSED_LINE = "Сезон закрыт"

_ARENA_SCHEDULE_MODE_SQL = "COALESCE(p.schedule_mode, 'auto')"


def arena_schedule_mode_sql(profile_alias: str = "p") -> str:
    """SQL fragment: normalized schedule_mode from arena_profiles alias."""
    if profile_alias != "p":
        return f"COALESCE({profile_alias}.schedule_mode, 'auto')"
    return _ARENA_SCHEDULE_MODE_SQL


def normalize_schedule_mode(value: Any) -> str:
    mode = str(value or SCHEDULE_MODE_AUTO).strip().lower()
    if mode not in SCHEDULE_MODES:
        raise ValueError("schedule_mode must be auto, phone, or season_closed")
    return mode


def _parse_reopen_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise ValueError("reopen_date must be YYYY-MM-DD") from None


def validate_schedule_mode_patch(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize admin patch fields; raises ValueError on bad combinations."""
    out: dict[str, Any] = {}
    if "schedule_mode" in fields:
        out["schedule_mode"] = normalize_schedule_mode(fields["schedule_mode"])
    mode = out.get("schedule_mode")
    if "reopen_date" in fields:
        out["reopen_date"] = _parse_reopen_date(fields["reopen_date"])
    if "schedule_mode_note" in fields:
        raw = fields["schedule_mode_note"]
        if raw is None or str(raw).strip() == "":
            out["schedule_mode_note"] = None
        else:
            note = str(raw).strip()
            if len(note) > 240:
                raise ValueError("schedule_mode_note must be at most 240 characters")
            out["schedule_mode_note"] = note
    if mode == SCHEDULE_MODE_AUTO:
        if out.get("reopen_date") is not None or out.get("schedule_mode_note"):
            raise ValueError("reopen_date and schedule_mode_note only apply when schedule_mode is season_closed")
    elif mode == SCHEDULE_MODE_PHONE:
        if out.get("reopen_date") is not None or out.get("schedule_mode_note"):
            raise ValueError("reopen_date and schedule_mode_note only apply when schedule_mode is season_closed")
    elif mode == SCHEDULE_MODE_SEASON_CLOSED:
        pass
    return out


def format_reopen_suffix(reopen: date | None) -> str:
    if reopen is None:
        return ""
    return f"откроется {reopen.day:02d}.{reopen.month:02d}"


def season_closed_user_line(
    *,
    reopen_date: date | None = None,
    note: str | None = None,
) -> str:
    parts = [SEASON_CLOSED_LINE]
    suffix = format_reopen_suffix(reopen_date)
    if suffix:
        parts.append(suffix)
    line = " · ".join(parts)
    note_s = str(note or "").strip()
    if note_s:
        return f"{line} — {note_s}"
    return line


def schedule_mode_live_kind(mode: str) -> str | None:
    if mode == SCHEDULE_MODE_PHONE:
        return "phone"
    if mode == SCHEDULE_MODE_SEASON_CLOSED:
        return "season_closed"
    return None


def schedule_mode_public_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    mode = normalize_schedule_mode(row.get("schedule_mode"))
    reopen = row.get("reopen_date")
    if isinstance(reopen, datetime):
        reopen = reopen.date()
    note = row.get("schedule_mode_note")
    note_s = str(note or "").strip() or None
    payload: dict[str, Any] = {
        "schedule_mode": mode,
        "schedule_reopen_date": reopen.isoformat() if reopen else None,
        "schedule_mode_note": note_s,
    }
    return payload


def is_schedule_mode_ice_today_eligible(mode: str) -> bool:
    return normalize_schedule_mode(mode) != SCHEDULE_MODE_SEASON_CLOSED
