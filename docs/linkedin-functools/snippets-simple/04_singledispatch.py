"""Simple snippet 4 of 4 — crop everything below the STUBS banner."""

from dataclasses import dataclass
from functools import singledispatch
from datetime import datetime
from decimal import Decimal

# 4. singledispatch — one entry point, different behaviour per type

# Before
def serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [serialize(v) for v in value]
    return str(value)

# After
@singledispatch
def serialize(value):
    return str(value)


@serialize.register
def _(value: datetime):
    return value.isoformat()


@serialize.register
def _(value: Decimal):
    return str(value)


@serialize.register
def _(value: list):
    return [serialize(v) for v in value]

# Add a type by registering a function — no growing isinstance ladder in one body.


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":
    print(serialize(datetime(2026, 8, 4, 12, 0)))
    print(serialize(Decimal("19.99")))
    print(serialize(["a", Decimal("1")]))
    # → 2026-08-04T12:00:00
    # → 19.99
    # → ['a', '1']
