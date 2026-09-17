"""IP-country resolution — the fast, zero-permission signal ahead of GPS geolocation."""
from __future__ import annotations

from src.shared.ip_geo import (
    SERVED_MARKET_COUNTRIES,
    is_ip_in_served_market,
    resolve_country_from_ip,
)

# Real, stable delegated ranges — not test/documentation ranges (192.0.2.0/24 etc. resolve
# to nothing in a country database, by design).
BELARUS_IP = "178.124.170.1"
RUSSIA_IP = "95.31.18.1"
US_IP = "8.8.8.8"


def test_resolves_belarus() -> None:
    assert resolve_country_from_ip(BELARUS_IP) == "BY"


def test_resolves_russia() -> None:
    assert resolve_country_from_ip(RUSSIA_IP) == "RU"


def test_resolves_a_clearly_unserved_country() -> None:
    assert resolve_country_from_ip(US_IP) == "US"


def test_returns_none_for_missing_or_unknown() -> None:
    assert resolve_country_from_ip(None) is None
    assert resolve_country_from_ip("") is None
    # client_ip_from_request's own fallback string when nothing usable was found.
    assert resolve_country_from_ip("unknown") is None


def test_returns_none_for_private_addresses() -> None:
    """Local dev / health checks must not be treated as a resolved (and therefore
    potentially "unserved") country — None means "we don't know", not "not served"."""
    assert resolve_country_from_ip("127.0.0.1") is None
    assert resolve_country_from_ip("10.0.0.5") is None
    assert resolve_country_from_ip("192.168.1.1") is None


def test_returns_none_for_garbage_input() -> None:
    assert resolve_country_from_ip("not-an-ip") is None


def test_served_market_countries_matches_the_pilot_scope() -> None:
    """PDEC-010/011/012: Belarus home market, Russia expansion, Serbia (Belgrade) pilot."""
    assert SERVED_MARKET_COUNTRIES == {"BY", "RU", "RS"}


def test_is_ip_in_served_market() -> None:
    assert is_ip_in_served_market(BELARUS_IP) is True
    assert is_ip_in_served_market(RUSSIA_IP) is True
    assert is_ip_in_served_market(US_IP) is False
    assert is_ip_in_served_market(None) is None
    assert is_ip_in_served_market("127.0.0.1") is None
