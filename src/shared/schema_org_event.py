"""schema.org Event fields recommended by Google Search (ice sessions on public pages)."""

from __future__ import annotations

from typing import Any, Mapping

SCHEMA_IN_STOCK = "https://schema.org/InStock"
SCHEMA_OUT_OF_STOCK = "https://schema.org/OutOfStock"


def _trim(text: str | None, limit: int = 500) -> str | None:
    if not text:
        return None
    cleaned = " ".join(str(text).split())
    if not cleaned:
        return None
    return cleaned[:limit] if len(cleaned) > limit else cleaned


def _organization(name: str | None, url: str | None) -> dict[str, Any] | None:
    label = _trim(name, 200)
    if not label:
        return None
    org: dict[str, Any] = {"@type": "Organization", "name": label}
    if url:
        org["url"] = url
    return org


def event_description(
    *,
    arena_name: str,
    session_label: str,
    short_description: str | None = None,
    address: str | None = None,
) -> str:
    """Plain-text description for Event JSON-LD."""
    custom = _trim(short_description, 400)
    if custom:
        return custom
    parts = [f"{session_label} на площадке «{arena_name}»."]
    addr = _trim(address, 200)
    if addr:
        parts.append(f"Адрес: {addr}.")
    parts.append("Актуальное расписание и цены — на странице места в Glide.")
    return " ".join(parts)


def build_session_offer(
    slot: Mapping[str, Any],
    *,
    url: str,
    availability: str = SCHEMA_IN_STOCK,
) -> dict[str, Any] | None:
    adult = slot.get("price_adult_minor")
    if adult is None:
        return None
    return {
        "@type": "Offer",
        "price": f"{int(adult) / 100:.2f}",
        "priceCurrency": slot.get("currency_code") or "BYN",
        "url": url,
        "availability": availability,
    }


def enrich_ice_session_event(
    event: dict[str, Any],
    *,
    arena_name: str,
    page_url: str,
    image_url: str | None,
    short_description: str | None = None,
    address: str | None = None,
    session_label: str,
    slot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Add organizer, performer, description, image; ensure offers.availability."""
    org = _organization(arena_name, page_url)
    if org:
        event["organizer"] = org
        event["performer"] = org
    desc = event_description(
        arena_name=arena_name,
        session_label=session_label,
        short_description=short_description,
        address=address,
    )
    event["description"] = desc
    if image_url:
        event["image"] = image_url
    if not event.get("url"):
        event["url"] = page_url

    slot = slot or {}
    status = str(slot.get("status") or "active").lower()
    availability = SCHEMA_OUT_OF_STOCK if status == "cancelled" else SCHEMA_IN_STOCK
    offers = event.get("offers")
    if isinstance(offers, dict):
        offers.setdefault("availability", availability)
    elif slot.get("price_adult_minor") is not None:
        built = build_session_offer(slot, url=page_url, availability=availability)
        if built:
            event["offers"] = built
    return event
