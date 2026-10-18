"""Админские операции с правилами типичной загрузки (TASK-290)."""
from __future__ import annotations

from datetime import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.session_load import (
    DAY_FRI,
    DAY_MON_THU,
    DAY_SAT,
    DAY_SUN,
    LOAD_LEVELS,
    invalidate_session_load_cache,
)

DAY_GROUPS = (DAY_MON_THU, DAY_FRI, DAY_SAT, DAY_SUN)
CHARACTERS = ("quiet", "steady", "hot")


def _hhmm(value: str) -> time:
    parts = value.strip().split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def _rule_row(row: tuple) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "scope": str(row[1]),
        "character": row[2],
        "arena_id": int(row[3]) if row[3] is not None else None,
        "day_group": str(row[4]),
        "starts_from": row[5].strftime("%H:%M") if row[5] else "00:00",
        "starts_before": row[6].strftime("%H:%M") if row[6] else None,
        "level": str(row[7]),
        "source": str(row[8]),
    }


async def list_global_load_rules(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT id, scope, character, arena_id, day_group,
                       starts_from, starts_before, level, source
                FROM session_load_rules
                WHERE scope = 'all'
                ORDER BY day_group, starts_from, id
                """
            )
        )
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {dg: [] for dg in DAY_GROUPS}
    for row in rows:
        item = _rule_row(row)
        grouped.setdefault(item["day_group"], []).append(item)
    return grouped


async def replace_global_day_rules(
    session: AsyncSession,
    *,
    day_group: str,
    intervals: list[dict[str, Any]],
) -> None:
    if day_group not in DAY_GROUPS:
        raise ValueError("day_group")
    await session.execute(
        text("DELETE FROM session_load_rules WHERE scope = 'all' AND day_group = :dg"),
        {"dg": day_group},
    )
    for band in intervals:
        level = str(band["level"])
        if level not in LOAD_LEVELS:
            raise ValueError("level")
        await session.execute(
            text(
                """
                INSERT INTO session_load_rules (
                    scope, character, arena_id, day_group,
                    starts_from, starts_before, level, source, updated_at
                )
                VALUES (
                    'all', NULL, NULL, :dg,
                    :starts_from, :starts_before, :level, 'admin', NOW()
                )
                """
            ),
            {
                "dg": day_group,
                "starts_from": _hhmm(str(band["starts_from"])),
                "starts_before": _hhmm(str(band["starts_before"])) if band.get("starts_before") else None,
                "level": level,
            },
        )
    invalidate_session_load_cache()


async def get_arena_load_admin(session: AsyncSession, arena_id: int) -> dict[str, Any]:
    char_row = (
        await session.execute(
            text("SELECT load_character FROM arena_profiles WHERE arena_id = :aid"),
            {"aid": int(arena_id)},
        )
    ).first()
    if char_row is None:
        raise LookupError("arena")
    rules = (
        await session.execute(
            text(
                """
                SELECT id, scope, character, arena_id, day_group,
                       starts_from, starts_before, level, source
                FROM session_load_rules
                WHERE scope = 'arena' AND arena_id = :aid
                ORDER BY day_group, starts_from, id
                """
            ),
            {"aid": int(arena_id)},
        )
    ).fetchall()
    arena_rules = [_rule_row(r) for r in rules]
    return {
        "arena_id": int(arena_id),
        "load_character": str(char_row[0]),
        "has_custom_rules": bool(arena_rules),
        "rules": arena_rules,
    }


async def set_arena_load_character(session: AsyncSession, arena_id: int, character: str) -> None:
    if character not in CHARACTERS:
        raise ValueError("character")
    result = await session.execute(
        text(
            """
            UPDATE arena_profiles
            SET load_character = :ch
            WHERE arena_id = :aid
            """
        ),
        {"ch": character, "aid": int(arena_id)},
    )
    if result.rowcount == 0:
        raise LookupError("arena")
    invalidate_session_load_cache()


async def replace_arena_day_rules(
    session: AsyncSession,
    *,
    arena_id: int,
    day_group: str,
    intervals: list[dict[str, Any]],
) -> None:
    if day_group not in DAY_GROUPS:
        raise ValueError("day_group")
    await session.execute(
        text(
            "DELETE FROM session_load_rules WHERE scope = 'arena' AND arena_id = :aid AND day_group = :dg"
        ),
        {"aid": int(arena_id), "dg": day_group},
    )
    for band in intervals:
        level = str(band["level"])
        if level not in LOAD_LEVELS:
            raise ValueError("level")
        await session.execute(
            text(
                """
                INSERT INTO session_load_rules (
                    scope, character, arena_id, day_group,
                    starts_from, starts_before, level, source, updated_at
                )
                VALUES (
                    'arena', NULL, :aid, :dg,
                    :starts_from, :starts_before, :level, 'admin', NOW()
                )
                """
            ),
            {
                "aid": int(arena_id),
                "dg": day_group,
                "starts_from": _hhmm(str(band["starts_from"])),
                "starts_before": _hhmm(str(band["starts_before"])) if band.get("starts_before") else None,
                "level": level,
            },
        )
    invalidate_session_load_cache()


async def reset_arena_load_rules(session: AsyncSession, arena_id: int) -> None:
    await session.execute(
        text("DELETE FROM session_load_rules WHERE scope = 'arena' AND arena_id = :aid"),
        {"aid": int(arena_id)},
    )
    invalidate_session_load_cache()
