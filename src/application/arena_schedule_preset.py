"""
Schedule start-time grid presets per arena. Trainer UI uses primary arena's preset when set;
otherwise trainer.schedule_grid_step_minutes (uniform_step).

Extensible: add new grid_kind values + allowed_start_minutes() branch.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# English note: keep in sync with arena_schedule_presets.grid_kind and schedule-editor JS.
GRID_QUARTER_15 = "quarter_15"
GRID_HOURLY_MINUTE = "hourly_minute"
GRID_UNIFORM_STEP = "uniform_step"

_TRAINER_GRID_STEPS = frozenset({10, 15, 30, 60})


def normalize_trainer_schedule_grid_step(raw: object | None) -> int:
    """Valid trainer preference for slots when arena has no preset row; default 15."""
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 15
    return n if n in _TRAINER_GRID_STEPS else 15


def default_quarter_preset() -> dict[str, Any]:
    return {
        "kind": GRID_QUARTER_15,
        "minute_offset": 0,
        "hour_start": 8,
        "hour_end": 21,
        "arena_id": None,
        "slot_duration_minutes": None,
        "step_minutes": 15,
    }


def trainer_uniform_preset(step_minutes: int) -> dict[str, Any]:
    """
    Grid when primary arena has no arena_schedule_presets row (or no primary).
    step_minutes is one of 10, 15, 30, 60.
    """
    step = normalize_trainer_schedule_grid_step(step_minutes)
    return {
        "kind": GRID_UNIFORM_STEP,
        "minute_offset": 0,
        "hour_start": 8,
        "hour_end": 21,
        "arena_id": None,
        "slot_duration_minutes": None,
        "step_minutes": step,
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
    if kind == GRID_UNIFORM_STEP:
        step = normalize_trainer_schedule_grid_step(preset.get("step_minutes"))
        return frozenset(range(h0 * 60, h1 * 60 + 1, step))
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
    Resolve grid from trainer's primary arena preset row if present; else trainer uniform step.
    """
    r = await session.execute(
        text("SELECT primary_arena_id, schedule_grid_step_minutes FROM trainers WHERE id = :tid"),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    primary = int(row[0]) if row and row[0] is not None else None
    trainer_step = normalize_trainer_schedule_grid_step(row[1] if row and len(row) > 1 else None)
    if primary is None:
        return trainer_uniform_preset(trainer_step)
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
        return trainer_uniform_preset(trainer_step)
    return {
        "kind": (row2[0] or GRID_QUARTER_15).strip(),
        "minute_offset": int(row2[1] or 0),
        "hour_start": int(row2[2] if row2[2] is not None else 8),
        "hour_end": int(row2[3] if row2[3] is not None else 21),
        "slot_duration_minutes": int(row2[4]) if row2[4] is not None else None,
        "arena_id": primary,
        "step_minutes": 15 if (row2[0] or GRID_QUARTER_15).strip() == GRID_QUARTER_15 else None,
    }


def schedule_grid_preset_to_api(preset: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe payload for GET /schedule."""
    raw_dur = preset.get("slot_duration_minutes")
    kind = (preset.get("kind") or GRID_QUARTER_15).strip()
    step_minutes: int | None
    if kind == GRID_UNIFORM_STEP:
        step_minutes = normalize_trainer_schedule_grid_step(preset.get("step_minutes"))
    elif kind == GRID_QUARTER_15:
        step_minutes = 15
    else:
        step_minutes = None
    return {
        "kind": kind,
        "minute_offset": int(preset.get("minute_offset", 0)),
        "hour_start": int(preset.get("hour_start", 8)),
        "hour_end": int(preset.get("hour_end", 21)),
        "arena_id": preset.get("arena_id"),
        "slot_duration_minutes": int(raw_dur) if raw_dur is not None else None,
        "step_minutes": step_minutes,
    }
