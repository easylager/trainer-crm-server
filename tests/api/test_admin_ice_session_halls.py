"""Админка: слоты разных залов одной арены (СДЮШОР Минск) не считаются пересечением."""
from __future__ import annotations

from datetime import date

import pytest

from src.application.ice_session_use_cases import (
    IceSessionOverlapError,
    apply_ice_session_patch,
    create_ice_session,
    validate_no_overlap,
)
from tests.api.test_public_arenas import _insert_arena, _insert_city

_DAY = date(2026, 12, 6)


async def _arena(db_session) -> int:
    city_id = await _insert_city(db_session, name="Минск")
    return await _insert_arena(db_session, city_id, name="СДЮШОР двухзальная")


async def _add(db_session, arena_id: int, hhmm: str, hall: str | None, kind: str = "public_skate") -> dict:
    return await create_ice_session(
        db_session,
        arena_id,
        local_date=_DAY,
        starts_at_local=hhmm,
        duration_minutes=60,
        kind=kind,
        hall=hall,
    )


@pytest.mark.asyncio
async def test_same_time_other_hall_is_allowed(db_session) -> None:
    arena_id = await _arena(db_session)
    main = await _add(db_session, arena_id, "17:15", "Главная арена", kind="figure_free")
    mass = await _add(db_session, arena_id, "17:15", "Тренировочная арена")
    assert main["hall"] == "Главная арена"
    assert mass["hall"] == "Тренировочная арена"


@pytest.mark.asyncio
async def test_same_hall_still_overlaps(db_session) -> None:
    arena_id = await _arena(db_session)
    await _add(db_session, arena_id, "17:15", "Главная арена")
    with pytest.raises(IceSessionOverlapError):
        await _add(db_session, arena_id, "17:30", "Главная арена")


@pytest.mark.asyncio
async def test_session_without_hall_overlaps_everything(db_session) -> None:
    arena_id = await _arena(db_session)
    await _add(db_session, arena_id, "17:15", "Главная арена")
    with pytest.raises(IceSessionOverlapError):
        await _add(db_session, arena_id, "17:30", None)


@pytest.mark.asyncio
async def test_patch_moves_session_between_halls(db_session) -> None:
    arena_id = await _arena(db_session)
    await _add(db_session, arena_id, "17:15", "Главная арена")
    other = await _add(db_session, arena_id, "19:00", "Тренировочная арена")
    updated = await apply_ice_session_patch(db_session, int(other["id"]), {"starts_at_local": "17:15"})
    assert updated["starts_at_local"] == "17:15"
    assert updated["hall"] == "Тренировочная арена"


def test_hall_names_compare_case_and_space_insensitively() -> None:
    from datetime import datetime, timedelta, timezone

    start = datetime(2026, 12, 6, 14, 0, tzinfo=timezone.utc)
    rows = [{"id": 1, "status": "active", "hall": " Главная арена ", "starts_at_utc": start, "ends_at_utc": start + timedelta(hours=1)}]
    with pytest.raises(IceSessionOverlapError):
        validate_no_overlap(rows, starts_at_utc=start, ends_at_utc=start + timedelta(hours=1), hall="главная арена")
    validate_no_overlap(rows, starts_at_utc=start, ends_at_utc=start + timedelta(hours=1), hall="Тренировочная арена")
