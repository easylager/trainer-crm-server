"""Shared Russian pluralization helpers."""

from __future__ import annotations


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
