"""Ice Discovery public scope — which countries' rinks the client Mini App shows.

Default is Belarus-only (V1 product scope lock, 2026-09-04). Configurable via
``ICE_DISCOVERY_COUNTRIES`` (comma-separated ISO country codes, e.g. ``"BY,RU"``)
for local/staging widening without touching the prod default.
"""
from __future__ import annotations

import os


def _parse_countries(raw: str) -> tuple[str, ...]:
    codes = tuple(sorted({c.strip().upper() for c in raw.split(",") if c.strip()}))
    return codes or ("BY",)


def ice_discovery_countries() -> tuple[str, ...]:
    """Re-reads the env on every call — cheap, and lets tests/local overrides take effect
    without needing a process restart or a cached Settings singleton reload."""
    return _parse_countries(os.environ.get("ICE_DISCOVERY_COUNTRIES", "BY"))


# Backward-compat: a fixed BY-only default some call sites may still import directly.
ICE_DISCOVERY_COUNTRY = "BY"
