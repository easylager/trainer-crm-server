"""Resolve client-facing brand: platform default or optional collective overlay."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from src.shared.config import Settings

DEFAULT_ACCENT_PRESET = "amber"
MAX_COLLECTIVE_GALLERY_ITEMS = 8

# Curated presets — owner picks id; client surfaces map to CSS vars.
ACCENT_PRESETS: dict[str, dict[str, str]] = {
    "amber": {
        "label": "Янтарь",
        "accent": "#F7A600",
        "accent_soft": "rgba(247, 166, 0, 0.14)",
        "accent_border": "rgba(247, 166, 0, 0.28)",
    },
    "slate": {
        "label": "Графит",
        "accent": "#5C6370",
        "accent_soft": "rgba(92, 99, 112, 0.12)",
        "accent_border": "rgba(92, 99, 112, 0.24)",
    },
    "forest": {
        "label": "Хвоя",
        "accent": "#2F6B4F",
        "accent_soft": "rgba(47, 107, 79, 0.12)",
        "accent_border": "rgba(47, 107, 79, 0.26)",
    },
    "rose": {
        "label": "Пыльная роза",
        "accent": "#B85C72",
        "accent_soft": "rgba(184, 92, 114, 0.12)",
        "accent_border": "rgba(184, 92, 114, 0.24)",
    },
    "ocean": {
        "label": "Океан",
        "accent": "#2B6CB0",
        "accent_soft": "rgba(43, 108, 176, 0.12)",
        "accent_border": "rgba(43, 108, 176, 0.24)",
    },
}


@dataclass(frozen=True)
class BrandPresentation:
    display_name: str
    tagline: str | None
    logo_key: str | None
    cover_key: str | None
    about: str | None
    gallery_keys: tuple[str, ...]
    accent_preset: str
    accent: dict[str, str]
    contacts: dict[str, str]
    powered_by: str
    collective_slug: str | None = None


def public_asset_url(file_key: str | None) -> str | None:
    key = (file_key or "").strip()
    if not key:
        return None
    return f"/api/public/photos/{quote(key, safe='')}"


def list_accent_preset_options() -> list[dict[str, str]]:
    return [{"id": pid, "label": meta["label"]} for pid, meta in ACCENT_PRESETS.items()]


def resolve_accent_preset(preset_id: str | None) -> dict[str, str]:
    pid = (preset_id or "").strip().lower() or DEFAULT_ACCENT_PRESET
    base = ACCENT_PRESETS.get(pid) or ACCENT_PRESETS[DEFAULT_ACCENT_PRESET]
    return {"id": pid if pid in ACCENT_PRESETS else DEFAULT_ACCENT_PRESET, **base}


def normalize_default_city_id(raw: Any) -> int | None:
    """Optional studio default catalog city stored in brand_tokens."""
    if raw is None or raw == "":
        return None
    try:
        city_id = int(raw)
    except (TypeError, ValueError):
        return None
    return city_id if city_id > 0 else None


def normalize_brand_tokens(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"accent_preset": DEFAULT_ACCENT_PRESET, "contacts": {}, "default_city_id": None}
    contacts_raw = raw.get("contacts")
    contacts: dict[str, str] = {}
    if isinstance(contacts_raw, dict):
        for field in ("address", "phone", "instagram", "telegram"):
            val = contacts_raw.get(field)
            if val is not None:
                contacts[field] = str(val).strip()[:500]
    preset = str(raw.get("accent_preset") or DEFAULT_ACCENT_PRESET).strip().lower()
    if preset not in ACCENT_PRESETS:
        preset = DEFAULT_ACCENT_PRESET
    return {
        "accent_preset": preset,
        "contacts": contacts,
        "default_city_id": normalize_default_city_id(raw.get("default_city_id")),
    }


def normalize_gallery_keys(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= MAX_COLLECTIVE_GALLERY_ITEMS:
            break
    return out


def platform_default_brand() -> BrandPresentation:
    settings = Settings()
    display = (settings.certificate_pdf_brand_display_name or "GLIDE").strip() or "GLIDE"
    accent = resolve_accent_preset(DEFAULT_ACCENT_PRESET)
    return BrandPresentation(
        display_name=display,
        tagline=None,
        logo_key=None,
        cover_key=None,
        about=None,
        gallery_keys=(),
        accent_preset=accent["id"],
        accent=accent,
        contacts={},
        powered_by=display,
        collective_slug=None,
    )


def resolve_brand_from_collective_row(row: dict[str, Any] | None) -> BrandPresentation:
    """Map a collective DB row to presentation; platform default when row is None."""
    platform = platform_default_brand()
    if not row:
        return platform
    slug = (row.get("slug") or "").strip() or None
    name = (row.get("display_name") or "").strip() or platform.display_name
    tagline = (row.get("tagline") or "").strip() or None
    logo_key = (row.get("logo_key") or "").strip() or None
    cover_key = (row.get("cover_key") or "").strip() or None
    about = (row.get("about") or "").strip() or None
    gallery_keys = tuple(normalize_gallery_keys(row.get("gallery_keys")))
    tokens = normalize_brand_tokens(row.get("brand_tokens"))
    accent = resolve_accent_preset(tokens["accent_preset"])
    return BrandPresentation(
        display_name=name,
        tagline=tagline,
        logo_key=logo_key,
        cover_key=cover_key,
        about=about,
        gallery_keys=gallery_keys,
        accent_preset=accent["id"],
        accent=accent,
        contacts=dict(tokens.get("contacts") or {}),
        powered_by=platform.display_name,
        collective_slug=slug,
    )


def brand_presentation_to_public_dict(brand: BrandPresentation, *, slug: str) -> dict[str, Any]:
    """JSON for GET /api/public/collectives/{slug}."""
    gallery = [
        {"key": key, "url": public_asset_url(key)}
        for key in brand.gallery_keys
        if key
    ]
    return {
        "slug": slug,
        "display_name": brand.display_name,
        "tagline": brand.tagline,
        "about": brand.about,
        "logo_key": brand.logo_key,
        "logo_url": public_asset_url(brand.logo_key),
        "cover_key": brand.cover_key,
        "cover_url": public_asset_url(brand.cover_key),
        "gallery": gallery,
        "accent_preset": brand.accent_preset,
        "accent": {
            "accent": brand.accent.get("accent"),
            "accent_soft": brand.accent.get("accent_soft"),
            "accent_border": brand.accent.get("accent_border"),
        },
        "contacts": brand.contacts,
        "powered_by": brand.powered_by,
    }
