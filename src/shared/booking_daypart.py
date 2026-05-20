"""
Fixed dayparts for per-client self-booking visibility (trainer CRM → client catalog/book).

Times are slot **start** in Europe/Minsk wall clock, inclusive bounds.
"""
from __future__ import annotations

from datetime import time
from typing import Any

BOOKING_DAYPART_MORNING = "morning"
BOOKING_DAYPART_AFTERNOON = "afternoon"
BOOKING_DAYPART_EVENING = "evening"

BOOKING_DAYPART_VALUES: frozenset[str] = frozenset(
    {BOOKING_DAYPART_MORNING, BOOKING_DAYPART_AFTERNOON, BOOKING_DAYPART_EVENING}
)

# (start inclusive, end inclusive) — trainer-facing windows from product spec
BOOKING_DAYPART_WINDOWS: dict[str, tuple[time, time]] = {
    BOOKING_DAYPART_MORNING: (time(8, 0), time(12, 0)),
    BOOKING_DAYPART_AFTERNOON: (time(13, 0), time(16, 0)),
    BOOKING_DAYPART_EVENING: (time(17, 0), time(22, 0)),
}

BOOKING_DAYPART_LABEL_RU: dict[str | None, str] = {
    None: "Любое время",
    BOOKING_DAYPART_MORNING: "Утро",
    BOOKING_DAYPART_AFTERNOON: "День",
    BOOKING_DAYPART_EVENING: "Вечер",
}

BOOKING_DAYPART_RANGES_HINT_RU = (
    "Утро 8:00–12:00 · День 13:00–16:00 · Вечер 17:00–22:00"
)


def normalize_booking_daypart(raw: object) -> str | None:
    """Return canonical daypart code or None (= no restriction)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    v = raw.strip().lower()
    if not v or v in ("any", "all", "none", "null"):
        return None
    return v if v in BOOKING_DAYPART_VALUES else None


def parse_slot_start_time(value: Any) -> time | None:
    """Parse slot start from DB row, API payload (HH:MM), or datetime.time."""
    if value is None:
        return None
    if isinstance(value, time):
        return value
    s = str(value).strip()
    if not s:
        return None
    if len(s) >= 5 and s[2] == ":":
        try:
            h, m = int(s[:2]), int(s[3:5])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return time(h, m, 0)
        except ValueError:
            return None
    return None


def slot_start_in_booking_daypart(start: time, daypart: str) -> bool:
    """True when slot start falls inside the daypart window."""
    window = BOOKING_DAYPART_WINDOWS.get(daypart)
    if window is None:
        return True
    lo, hi = window
    return lo <= start <= hi


def slot_dict_matches_booking_daypart(slot: dict[str, Any], daypart: str) -> bool:
    st = parse_slot_start_time(slot.get("start_time"))
    if st is None:
        return False
    return slot_start_in_booking_daypart(st, daypart)


def booking_daypart_trainer_options() -> list[dict[str, str | None]]:
    """Options for segmented control in trainer client card."""
    out: list[dict[str, str | None]] = [
        {"value": None, "label": BOOKING_DAYPART_LABEL_RU[None]},
    ]
    for code in (BOOKING_DAYPART_MORNING, BOOKING_DAYPART_AFTERNOON, BOOKING_DAYPART_EVENING):
        out.append({"value": code, "label": BOOKING_DAYPART_LABEL_RU[code]})
    return out


def booking_daypart_api_payload(daypart: str | None) -> dict[str, Any]:
    return {
        "value": daypart,
        "label": BOOKING_DAYPART_LABEL_RU.get(daypart, BOOKING_DAYPART_LABEL_RU[None]),
        "ranges_hint": BOOKING_DAYPART_RANGES_HINT_RU,
        "options": booking_daypart_trainer_options(),
    }
