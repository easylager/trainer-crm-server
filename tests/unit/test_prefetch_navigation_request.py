"""FEEL-A: prefetch-навигация не считается просмотром публички."""

from __future__ import annotations

from starlette.requests import Request

from src.application.catalog_consumer_events import is_prefetch_navigation_request


def _req(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/p/minsk/test",
        "headers": [
            (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()
        ],
    }
    return Request(scope)


def test_prefetch_sec_purpose() -> None:
    assert is_prefetch_navigation_request(_req({"Sec-Purpose": "prefetch"}))


def test_prefetch_legacy_purpose_header() -> None:
    assert is_prefetch_navigation_request(_req({"Purpose": "prefetch"}))


def test_normal_navigation_is_not_prefetch() -> None:
    assert not is_prefetch_navigation_request(_req({"User-Agent": "Mozilla/5.0"}))
