"""Ровная сетка сеансов сворачивается в одну фразу. Неровная остаётся списком времён."""

from __future__ import annotations

from src.shared.public_display import format_clock


def _minutes(clock: str) -> int | None:
    shown = format_clock(clock)
    if len(shown) < 4 or ":" not in shown:
        return None
    hour, minute = shown.split(":", 1)
    if not hour.isdigit() or not minute.isdigit():
        return None
    return int(hour) * 60 + int(minute)


def _interval(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} ч")
    if mins:
        parts.append(f"{mins} мин")
    return " ".join(parts)


def collapse_even_grid(times: list[str]) -> str | None:
    """«с 12:30 каждые 1 ч 15 мин», если шаг один и сеансов хотя бы три.

    Два времени или разный шаг — None: на странице остаются сами часы.
    """
    minutes = [m for raw in times if (m := _minutes(raw)) is not None]
    if len(minutes) < 3 or len(minutes) != len(times):
        return None
    minutes.sort()
    if len(set(minutes)) != len(minutes):
        return None
    deltas = [b - a for a, b in zip(minutes, minutes[1:])]
    if len(set(deltas)) != 1 or deltas[0] <= 0:
        return None
    start = format_clock(f"{minutes[0] // 60}:{minutes[0] % 60:02d}")
    return f"с {start} каждые {_interval(deltas[0])}"
