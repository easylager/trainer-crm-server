"""Config-driven weekly mass-skate grid (TASK-205): no HTTP, schedule_basis=projected."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from src.ingestion.dates import minsk_today
from src.ingestion.parsers import IceParser
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob
from src.shared.schedule_basis import SCHEDULE_BASIS_PROJECTED


def _fmt(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _hhmm_to_minutes(value: str) -> int:
    parts = str(value).strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _minutes_to_hhmm(total: int) -> str:
    total %= 24 * 60
    return _fmt(total // 60, total % 60)


def _end_time(start: str, duration_minutes: int) -> str:
    start_m = _hhmm_to_minutes(start)
    return _minutes_to_hhmm(start_m + duration_minutes)


def _session_overlaps_window(
    start: str,
    duration_minutes: int,
    window_start: str,
    window_end: str,
) -> bool:
    s0 = _hhmm_to_minutes(start)
    s1 = s0 + duration_minutes
    w0 = _hhmm_to_minutes(window_start)
    w1 = _hhmm_to_minutes(window_end)
    return s0 < w1 and s1 > w0


def _weekday_window(config: Mapping[str, Any], weekday: int) -> tuple[str, str] | None:
    raw = config.get("weekday_windows") or {}
    entry = raw.get(str(weekday)) or raw.get(weekday)
    if not entry:
        return None
    open_at = str(entry.get("open") or "").strip()
    close_at = str(entry.get("close") or "").strip()
    if not open_at or not close_at:
        return None
    return open_at, close_at


def _excluded_for_weekday(config: Mapping[str, Any], weekday: int) -> list[tuple[str, str]]:
    raw = config.get("excluded_windows") or {}
    windows = raw.get(str(weekday)) or raw.get(weekday) or []
    out: list[tuple[str, str]] = []
    for item in windows:
        if not isinstance(item, Mapping):
            continue
        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or "").strip()
        if start and end:
            out.append((start, end))
    return out


def _is_weekend_price_day(weekday: int, config: Mapping[str, Any]) -> bool:
    explicit = config.get("weekend_weekdays")
    if explicit is not None:
        return int(weekday) in {int(x) for x in explicit}
    return weekday >= 4


def _prices_for_day(weekday: int, config: Mapping[str, Any]) -> tuple[int | None, int | None, int | None]:
    key = "price_weekend" if _is_weekend_price_day(weekday, config) else "price_weekday"
    block = config.get(key) or {}
    adult = block.get("adult")
    child = block.get("child")
    rental = block.get("rental")
    return (
        int(adult) if adult is not None else None,
        int(child) if child is not None else None,
        int(rental) if rental is not None else None,
    )


def iter_grid_starts(open_at: str, close_at: str, *, step_minutes: int) -> list[str]:
    """Last start = close − step (Q-001: close hour is rink shutdown, not session start)."""
    open_m = _hhmm_to_minutes(open_at)
    close_m = _hhmm_to_minutes(close_at)
    last_start_m = close_m - step_minutes
    if last_start_m < open_m:
        return []
    starts: list[str] = []
    t = open_m
    while t <= last_start_m:
        starts.append(_minutes_to_hhmm(t))
        t += step_minutes
    return starts


def build_weekly_grid_slots(job: ParserJob) -> list[ExtractedSlot]:
    cfg = job.config
    horizon = int(cfg.get("horizon_days") or 14)
    step = int(cfg.get("step_minutes") or 60)
    duration = int(cfg.get("duration_minutes") or cfg.get("default_duration_minutes") or 45)
    run_date_raw = cfg.get("run_date")
    run_date = date.fromisoformat(str(run_date_raw)) if run_date_raw else minsk_today()
    kind_raw = str(cfg.get("kind") or "public_skate")
    raw_age = cfg.get("age_note")
    age_note = str(raw_age).strip() if raw_age else None
    slots: list[ExtractedSlot] = []
    for offset in range(horizon):
        local_date = run_date + timedelta(days=offset)
        weekday = local_date.weekday()
        window = _weekday_window(cfg, weekday)
        if not window:
            continue
        open_at, close_at = window
        excluded = _excluded_for_weekday(cfg, weekday)
        adult, child, rental = _prices_for_day(weekday, cfg)
        for start in iter_grid_starts(open_at, close_at, step_minutes=step):
            if any(
                _session_overlaps_window(start, duration, w_start, w_end)
                for w_start, w_end in excluded
            ):
                continue
            slots.append(
                ExtractedSlot(
                    local_date=local_date.isoformat(),
                    starts_at_local=start,
                    ends_at_local=_end_time(start, duration),
                    kind_raw=kind_raw,
                    price_adult=adult,
                    price_child=child,
                    price_rental=rental,
                    age_note=age_note,
                )
            )
    return slots


class WeeklyGridV1Parser(IceParser):
    parser_key = "weekly_grid_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        slots = build_weekly_grid_slots(job)
        snapshot = json.dumps(
            {
                "parser_key": self.parser_key,
                "horizon_days": job.config.get("horizon_days"),
                "run_date": job.config.get("run_date") or minsk_today().isoformat(),
                "slot_count": len(slots),
            },
            ensure_ascii=False,
        )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=snapshot,
            slots=slots,
            schedule_basis=SCHEDULE_BASIS_PROJECTED,
        )
