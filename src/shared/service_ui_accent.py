"""Preset slugs for per-trainer-service UI border accent (hub + schedule)."""

from __future__ import annotations

# Keep in sync with CSS classes: .slot-row--svc-accent-<slug>
SERVICE_UI_ACCENT_SLUGS: frozenset[str] = frozenset(
    {"sky", "amber", "emerald", "violet", "rose", "slate"}
)


def normalize_service_ui_accent(raw: object) -> str | None:
    """Return a valid slug or None (clear / unset)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if not s:
        return None
    return s if s in SERVICE_UI_ACCENT_SLUGS else None
