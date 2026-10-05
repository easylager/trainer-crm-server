"""Calendar helpers for ingestion adapters (Europe/Minsk business dates)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

MINSK_TZ = ZoneInfo("Europe/Minsk")

_WINDOW_PAST_DAYS = 30
_WINDOW_FUTURE_DAYS = 330


def minsk_today() -> date:
    return datetime.now(MINSK_TZ).date()


def parser_reference_date(config: dict[str, Any] | None = None) -> date:
    """Anchor for inferring calendar dates from day+month fragments."""
    config = config or {}
    if config.get("run_date"):
        return date.fromisoformat(str(config["run_date"]))
    if config.get("run_year"):
        # Mid-season anchor keeps run_year-only fixture grids inside the inference window.
        return date(int(config["run_year"]), 7, 1)
    return minsk_today()


def infer_date_from_day_month(day: int, month: int, reference: date) -> date | None:
    """Map day+month to the nearest calendar date within ±window of reference."""
    best: date | None = None
    best_abs: int | None = None
    best_delta: int | None = None
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        delta = (candidate - reference).days
        if delta < -_WINDOW_PAST_DAYS or delta > _WINDOW_FUTURE_DAYS:
            continue
        abs_delta = abs(delta)
        if best is None or abs_delta < best_abs or (abs_delta == best_abs and delta > best_delta):
            best = candidate
            best_abs = abs_delta
            best_delta = delta
    return best
