"""TASK-205: config-driven weekly mass-skate grid (projected, no HTTP)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.ingestion.seed_config_mozyr_global_ice import MOZYR_GLOBAL_ICE_CONFIG
from src.ingestion.types import ParserJob
from src.ingestion.weekly_grid_v1 import WeeklyGridV1Parser, build_weekly_grid_slots
from src.shared.schedule_basis import SCHEDULE_BASIS_PROJECTED


def _job(config: dict) -> ParserJob:
    return ParserJob(
        id=1,
        arena_id=205,
        parser_key="weekly_grid_v1",
        is_enabled=True,
        cadence="daily",
        next_run_at=datetime.now(timezone.utc),
        last_run_at=None,
        config=config,
    )


def _slots_by_date(config: dict) -> dict[str, list[str]]:
    slots = build_weekly_grid_slots(_job(config))
    out: dict[str, list[str]] = {}
    for slot in slots:
        out.setdefault(slot.local_date, []).append(slot.starts_at_local)
    for day in out:
        out[day].sort()
    return out


def test_mozyr_week_grid_counts_and_exclusions() -> None:
    cfg = {**MOZYR_GLOBAL_ICE_CONFIG, "run_date": "2026-10-05", "horizon_days": 7}
    by_day = _slots_by_date(cfg)
    assert len(by_day["2026-10-05"]) == 8  # Mon: 9 starts, drop 18:00
    assert len(by_day["2026-10-06"]) == 8
    assert len(by_day["2026-10-07"]) == 8
    assert len(by_day["2026-10-08"]) == 9  # Thu: no hockey block
    assert len(by_day["2026-10-09"]) == 10  # Fri
    assert len(by_day["2026-10-10"]) == 11  # Sat
    assert len(by_day["2026-10-11"]) == 10  # Sun
    assert "18:00" not in by_day["2026-10-05"]
    assert by_day["2026-10-05"][-1] == "19:00"
    assert by_day["2026-10-09"][-1] == "21:00"
    assert by_day["2026-10-11"][-1] == "20:00"


def test_mozyr_weekday_vs_weekend_prices() -> None:
    cfg = {**MOZYR_GLOBAL_ICE_CONFIG, "run_date": "2026-10-05", "horizon_days": 7}
    slots = build_weekly_grid_slots(_job(cfg))
    mon = next(s for s in slots if s.local_date == "2026-10-05" and s.starts_at_local == "11:00")
    fri = next(s for s in slots if s.local_date == "2026-10-09" and s.starts_at_local == "11:00")
    assert mon.price_adult == 900 and mon.price_child == 600 and mon.price_rental == 700
    assert fri.price_adult == 1000 and fri.price_child == 700 and fri.price_rental == 700


@pytest.mark.asyncio
async def test_extract_marks_projected_without_network() -> None:
    cfg = {**MOZYR_GLOBAL_ICE_CONFIG, "run_date": "2026-10-05", "horizon_days": 2}
    extraction = await WeeklyGridV1Parser().extract(_job(cfg))
    assert extraction.schedule_basis == SCHEDULE_BASIS_PROJECTED
    assert extraction.slots
    assert extraction.parser_key == "weekly_grid_v1"


def test_horizon_crosses_year_boundary() -> None:
    cfg = {**MOZYR_GLOBAL_ICE_CONFIG, "run_date": "2025-12-30", "horizon_days": 5}
    by_day = _slots_by_date(cfg)
    assert "2025-12-30" in by_day
    assert "2026-01-01" in by_day
    assert "2026-01-03" in by_day
    assert len(by_day) == 5
