"""Shared Russian pluralization helpers."""

from __future__ import annotations

import math
from typing import Any


def plural_ru(number: int | float, one: str, few: str, many: str) -> str:
    absolute = abs(int(number))
    last_two = absolute % 100
    last = absolute % 10
    if 11 <= last_two <= 14:
        return many
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def count_ru(number: int | float, one: str, few: str, many: str) -> str:
    return f"{number} {plural_ru(number, one, few, many)}"


def trainer_rating_score(avg: Any) -> float | None:
    """Одна десятая, half-up — как ``RuText.trainerRatingScore`` в Mini App (4,25 → 4,3)."""
    if avg is None:
        return None
    try:
        value = float(avg)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return math.floor(value * 10 + 0.5) / 10


def trainer_rating_parts(avg: Any, count: Any) -> tuple[str, str] | None:
    """(«5,0», «2 оценки») с первой оценки. Нет оценок — None: ни «0», ни пустых звёзд."""
    try:
        n = int(count or 0)
    except (TypeError, ValueError):
        return None
    if n < 1:
        return None
    value = trainer_rating_score(avg)
    if value is None:
        return None
    score = f"{value:.1f}".replace(".", ",")
    return score, count_ru(n, "оценка", "оценки", "оценок")


def trainer_rating_summary(avg: Any, count: Any) -> str:
    """Подпись под звёздами на /t/: «1 оценка — 5 из 5», «7 оценок — все на 5 из 5»."""
    parts = trainer_rating_parts(avg, count)
    if not parts:
        return ""
    score, label = parts
    value = trainer_rating_score(avg)
    if value is None:
        return ""
    n = int(count or 0)
    perfect = f"{int(value)}" if value == int(value) else score
    if n == 1:
        if value >= 5:
            return f"{label} — {perfect} из 5"
        return f"{label}, в среднем {score} из 5"
    if value >= 5:
        return f"{label} — все на 5 из 5"
    return f"{label}, в среднем {score} из 5"


def trainer_rating_caption(avg: Any, count: Any) -> str:
    """«★ 5,0 · 2 оценки». Пустая строка, если показывать нечего."""
    parts = trainer_rating_parts(avg, count)
    if not parts:
        return ""
    score, label = parts
    return f"★ {score} · {label}"
