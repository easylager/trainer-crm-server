"""IP-based country resolution — the fast, zero-permission signal for "which market is this
visitor probably in", used ahead of (never instead of) browser geolocation.

Why this exists: the client catalog/hub previously had no signal at all for a visitor with no
saved city except asking the browser for GPS coordinates — a permission prompt most visitors
will never see a reason to grant on a cold, contextless first open. Nearly every mature
multi-region consumer product (Uber, Wolt, Airbnb, Booking) resolves country from IP first,
with zero prompts, and only asks for precise location as an optional refinement. This module
is that first layer: cheap, in-process, no third-party network call, no signup/license key.

Uses ``geoip2fast`` (MIT, bundled country-level database, no external calls at runtime) rather
than a hosted IP-geolocation API — no per-request latency/rate-limit dependency on a third
party, no client IPs leaving our own infrastructure.
"""
from __future__ import annotations

from functools import lru_cache

# Countries where the platform has real content today (Belarus home market, Russia expansion,
# the Belgrade/Serbia pilot — see PDEC-010/011/012, docs/research/b2b-studio-market-serbia).
# Country-level only (this DB has no city granularity) — a visitor in a served country may
# still be far from any actual arena/trainer; that's what the GPS-based distance refinement
# (catalog-geo-model.js / ice-teaser-model.js) is for. This set only answers "is it worth
# asking for more precision at all", not "exactly where are they".
SERVED_MARKET_COUNTRIES = {"BY", "RU", "RS"}


@lru_cache(maxsize=1)
def _geoip_instance():
    """Loaded once per process — the bundled .dat is read from disk on first lookup only."""
    from geoip2fast import GeoIP2Fast

    return GeoIP2Fast(verbose=False)


def resolve_country_from_ip(ip: str | None) -> str | None:
    """ISO-3166 alpha-2 country code for ``ip``, or ``None`` when unresolvable.

    ``None`` (not "unserved") for anything we can't confidently resolve — private/loopback
    addresses (local dev, health checks), "unknown" (client_ip_from_request's own fallback),
    or a lookup miss. Callers must treat ``None`` as "we don't know", never as "not served" —
    punishing a visitor for a lookup failure would be worse than just falling through to the
    existing GPS-based path.
    """
    if not ip or ip == "unknown":
        return None
    try:
        result = _geoip_instance().lookup(ip)
    except Exception:
        return None
    if result is None or result.is_private:
        return None
    code = (result.country_code or "").strip().upper()
    return code or None


def is_ip_in_served_market(ip: str | None) -> bool | None:
    """True/False when the IP's country is confidently known; None when we couldn't tell."""
    country = resolve_country_from_ip(ip)
    if country is None:
        return None
    return country in SERVED_MARKET_COUNTRIES
