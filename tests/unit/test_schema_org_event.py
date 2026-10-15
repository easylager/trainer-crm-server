"""schema.org Event enrichment for public ice pages."""

from __future__ import annotations

from src.shared.schema_org_event import (
    SCHEMA_IN_STOCK,
    enrich_ice_session_event,
    event_description,
)


def test_enrich_adds_recommended_fields() -> None:
    event = {
        "@type": "Event",
        "name": "Массовое — Каток",
        "offers": {
            "@type": "Offer",
            "price": "8.50",
            "priceCurrency": "BYN",
            "url": "https://glideclub.by/p/minsk/katok",
        },
    }
    enrich_ice_session_event(
        event,
        arena_name="Каток",
        page_url="https://glideclub.by/p/minsk/katok",
        image_url="https://glideclub.by/p/minsk/katok/og.png",
        short_description="Прокат на месте.",
        address="ул. Ледовая, 1",
        session_label="Массовое катание",
        slot={"price_adult_minor": 850, "status": "active"},
    )
    assert event["description"] == "Прокат на месте."
    assert event["image"].endswith("/og.png")
    assert event["organizer"]["name"] == "Каток"
    assert event["performer"]["name"] == "Каток"
    assert event["offers"]["availability"] == SCHEMA_IN_STOCK


def test_description_fallback_when_no_short_text() -> None:
    text = event_description(
        arena_name="Арена",
        session_label="Массовое катание",
        address="Минск",
    )
    assert "Арена" in text
    assert "Glide" in text
