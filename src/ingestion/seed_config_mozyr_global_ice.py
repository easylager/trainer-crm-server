"""job.config for Global ICE Мозырь (weekly_grid_v1) — no live schedule URL."""

from __future__ import annotations

PARSER_KEY_WEEKLY_GRID_V1 = "weekly_grid_v1"

# Prices in minor units (kopecks): 9/6/7 BYN weekday, 10/7/7 weekend.
MOZYR_GLOBAL_ICE_CONFIG: dict = {
    "schedule_basis": "projected",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "horizon_days": 14,
    "step_minutes": 60,
    "duration_minutes": 45,
    "default_duration_minutes": 45,
    "prices_already_minor": True,
    "requires_by_egress": False,
    "weekday_windows": {
        "0": {"open": "11:00", "close": "20:00"},
        "1": {"open": "11:00", "close": "20:00"},
        "2": {"open": "11:00", "close": "20:00"},
        "3": {"open": "11:00", "close": "20:00"},
        "4": {"open": "11:00", "close": "22:00"},
        "5": {"open": "11:00", "close": "22:00"},
        "6": {"open": "11:00", "close": "21:00"},
    },
    "excluded_windows": {
        "0": [{"start": "17:45", "end": "18:45"}],
        "1": [{"start": "17:45", "end": "18:45"}],
        "2": [{"start": "17:45", "end": "18:45"}],
        "4": [{"start": "17:45", "end": "18:45"}],
    },
    "weekend_weekdays": [4, 5, 6],
    "price_weekday": {"adult": 900, "child": 600, "rental": 700},
    "price_weekend": {"adult": 1000, "child": 700, "rental": 700},
    "source_note": "Instagram @global_ice_, owner 2026-10-07",
}
