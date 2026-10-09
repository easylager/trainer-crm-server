"""Форматирование метрик атрибуции шаринга (TASK-223)."""

from __future__ import annotations

from src.application.catalog_consumer_events import (
    format_share_attribution_report_lines,
    public_page_view_attribution_payload,
)


def test_public_page_view_attribution_payload_filters_keys() -> None:
    assert public_page_view_attribution_payload({"src": "tg", "s": "7", "i": "1", "evil": "x"}) == {
        "src": "tg",
        "s": "7",
        "i": "1",
    }
    assert public_page_view_attribution_payload({"src": "nope", "s": "0"}) == {}


def test_format_share_attribution_report_lines() -> None:
    lines = format_share_attribution_report_lines(
        {
            "public_page_view_by_src": {"tg": 3, "wa": 1},
            "public_page_view_with_session": 2,
            "public_telegram_cta_clicks_by_src": {"tg": 1},
        }
    )
    assert any("tg: 3" in line for line in lines)
    assert any("?s=" in line for line in lines)
    assert format_share_attribution_report_lines({}) == []


def test_dedup_hash_variant_separates_channels_and_keeps_legacy_key() -> None:
    from datetime import date

    from src.application.catalog_consumer_events import event_dedup_hash

    base = dict(kind="public_page_view", surface="place_page", actor_hash="a" * 16, day=date(2026, 10, 9), arena_id=7)
    legacy = event_dedup_hash(**base)
    assert legacy == event_dedup_hash(**base, variant=None)
    tg = event_dedup_hash(**base, variant="tg")
    wa = event_dedup_hash(**base, variant="wa")
    assert len({legacy, tg, wa}) == 3
