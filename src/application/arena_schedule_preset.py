"""
Schedule start-time grid presets per arena. Trainer UI uses primary arena's preset when set.

Extensible: add new grid_kind values + allowed_start_minutes() branch.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# English note: keep in sync with arena_schedule_presets.grid_kind and schedule-editor JS.
GRID_QUARTER_15 = "quarter_15"
GRID_HOURLY_MINUTE = "hourly_minute"


def default_quarter_preset() -> dict[str, Any]:
    return {
        "kind": GRID_QUARTER_15,
        "minute_offset": 0,
        "hour_start": 8,
        "hour_end": 21,
        "arena_id": None,
        "slot_duration_minutes": None,
    }


def fixed_slot_duration_minutes(preset: dict[str, Any]) -> int | None:
    """When set, all new slots/templates/quick-book must use this duration."""
    raw = preset.get("slot_duration_minutes")
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < 15 or n > 24 * 60:
        return None
    return n


def validate_duration_for_preset(duration_minutes: int, preset: dict[str, Any]) -> None:
    fixed = fixed_slot_duration_minutes(preset)
    if fixed is None:
        return
    if int(duration_minutes) != fixed:
        raise ValueError(
            "Длительность зафиксирована для площадки этой сетки — используйте указанное значение."
        )


def allowed_start_minutes_from_preset(preset: dict[str, Any]) -> frozenset[int]:
    """All valid slot start minutes (from midnight) for this preset."""
    kind = (preset.get("kind") or GRID_QUARTER_15).strip()
    h0 = max(0, min(23, int(preset.get("hour_start", 8))))
    h1 = max(0, min(23, int(preset.get("hour_end", 21))))
    if h1 < h0:
        h0, h1 = h1, h0
    if kind == GRID_HOURLY_MINUTE:
        mo = max(0, min(59, int(preset.get("minute_offset", 0))))
        return frozenset(h * 60 + mo for h in range(h0, h1 + 1))
    # quarter_15: 15 min steps from h0:00 through h1:00 inclusive
    return frozenset(range(h0 * 60, h1 * 60 + 1, 15))


def validate_start_minutes_for_preset(minutes: set[int], preset: dict[str, Any]) -> None:
    """Raises ValueError if any minute is not on the arena grid."""
    allowed = allowed_start_minutes_from_preset(preset)
    bad = {int(x) for x in minutes} - allowed
    if bad:
        raise ValueError("Время начала не соответствует сетке площадки. Выберите допустимое время.")


async def get_schedule_grid_preset_for_trainer(
    session: AsyncSession,
    trainer_id: int,
) -> dict[str, Any]:
    """
    Resolve grid from trainer's primary arena preset row, else default quarter-hour grid.
    """
    r = await session.execute(
        text("SELECT primary_arena_id FROM trainers WHERE id = :tid"),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    primary = int(row[0]) if row and row[0] is not None else None
    if primary is None:
        return default_quarter_preset()
    r2 = await session.execute(
        text(
            """
            SELECT grid_kind, minute_offset, hour_start, hour_end, slot_duration_minutes
            FROM arena_schedule_presets
            WHERE arena_id = :aid
            """
        ),
        {"aid": primary},
    )
    row2 = r2.fetchone()
    if not row2:
        return default_quarter_preset()
    return {
        "kind": (row2[0] or GRID_QUARTER_15).strip(),
        "minute_offset": int(row2[1] or 0),
        "hour_start": int(row2[2] if row2[2] is not None else 8),
        "hour_end": int(row2[3] if row2[3] is not None else 21),
        "slot_duration_minutes": int(row2[4]) if row2[4] is not None else None,
        "arena_id": primary,
    }


def schedule_grid_preset_to_api(preset: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe payload for GET /schedule."""
    raw_dur = preset.get("slot_duration_minutes")
    return {
        "kind": preset.get("kind") or GRID_QUARTER_15,
        "minute_offset": int(preset.get("minute_offset", 0)),
        "hour_start": int(preset.get("hour_start", 8)),
        "hour_end": int(preset.get("hour_end", 21)),
        "arena_id": preset.get("arena_id"),
        "slot_duration_minutes": int(raw_dur) if raw_dur is not None else None,
    }
