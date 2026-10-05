"""Ice Discovery public scope — which countries' rinks the client Mini App shows.

Default is Belarus-only (V1 product scope lock, 2026-09-04). Configurable via
``ICE_DISCOVERY_COUNTRIES`` (comma-separated ISO country codes, e.g. ``"BY,RU"``)
for local/staging widening without touching the prod default.
"""
from __future__ import annotations

import os
from typing import Any, Mapping


def _parse_countries(raw: str) -> tuple[str, ...]:
    codes = tuple(sorted({c.strip().upper() for c in raw.split(",") if c.strip()}))
    return codes or ("BY",)


def ice_discovery_countries() -> tuple[str, ...]:
    """Re-reads the env on every call — cheap, and lets tests/local overrides take effect
    without needing a process restart or a cached Settings singleton reload."""
    return _parse_countries(os.environ.get("ICE_DISCOVERY_COUNTRIES", "BY"))


# Backward-compat: a fixed BY-only default some call sites may still import directly.
ICE_DISCOVERY_COUNTRY = "BY"


# ---------------------------------------------------------------------------
# TASK-177: one visibility predicate for every public catalog surface.
#
# Before this, each public query re-typed its own subset of the rules and they
# drifted: the list and the map bbox ignored ``cities.is_active`` (a deactivated
# Moscow kept 100 cards online), the sitemap listed trainer-created arenas whose
# page 404s, ``/c/`` and ``/ice/{city}`` resolved cities of any country.
#
# Contract: the query aliases ``arenas a``, ``cities c`` (joined on a.city_id) and
# ``arena_profiles p`` (LEFT JOIN is fine) and binds ``:ice_countries`` — see
# ``public_scope_params()``.
# ---------------------------------------------------------------------------

#: A city whose places may appear publicly: active and inside the discovery countries.
PUBLIC_CITY_SCOPE_SQL = "c.is_active AND c.country = ANY(:ice_countries)"

#: An arena that may appear on any public surface (list, map bbox, search, card,
#: sitemap, /p/, /c/, /ice/{city}/today, hub teaser, landing counters).
PUBLIC_ARENA_VISIBLE_SQL = (
    "a.is_active AND a.is_confirmed"
    f" AND {PUBLIC_CITY_SCOPE_SQL}"
    " AND (p.status IS NULL OR p.status = 'published')"
    # A trainer-created arena with no photo is an admin task in progress, not a place
    # to send people; the seeded/imported catalog is exempt (see _LIST_SQL history).
    " AND (a.created_by_trainer_id IS NULL OR EXISTS ("
    "SELECT 1 FROM media m WHERE m.owner_type = 'arena' AND m.owner_id = a.id"
    " AND m.status = 'published'))"
)


def public_city_scope_sql(alias: str = "c") -> str:
    """``PUBLIC_CITY_SCOPE_SQL`` for a ``cities`` alias other than ``c``."""
    if not alias.isidentifier():
        raise ValueError(f"bad SQL alias: {alias!r}")
    return f"{alias}.is_active AND {alias}.country = ANY(:ice_countries)"


def public_scope_params() -> dict[str, list[str]]:
    """Bind params the predicates above need."""
    return {"ice_countries": list(ice_discovery_countries())}


def arena_publicly_visible_row(
    row: Mapping[str, Any],
    *,
    ice_countries: tuple[str, ...] | None = None,
) -> bool:
    """Python mirror of ``PUBLIC_ARENA_VISIBLE_SQL`` for audit/report code paths."""
    countries = ice_countries or ice_discovery_countries()
    if not row.get("is_active") or not row.get("is_confirmed"):
        return False
    if not row.get("city_is_active", True):
        return False
    country = str(row.get("city_country") or row.get("country") or "").strip().upper()
    if country not in countries:
        return False
    status = row.get("profile_status")
    if status is not None and status != "published":
        return False
    if row.get("created_by_trainer_id") is not None and not row.get("has_photo"):
        return False
    return True
