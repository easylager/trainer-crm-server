"""Validate CanonicalSlotDraft before any publisher (TASK-061) may persist."""
from __future__ import annotations

from src.application.ice_session_use_cases import (
    IceSessionOverlapError,
    IceSessionValidationError,
    duration_minutes,
    validate_duration_minutes,
    validate_prices,
)
from src.ingestion.types import PARSER_KINDS, CanonicalSlotDraft


class IceSessionValidator:
    def validate(self, drafts: list[CanonicalSlotDraft]) -> list[CanonicalSlotDraft]:
        seen_starts: set[tuple[int, object]] = set()
        validated: list[CanonicalSlotDraft] = []
        for draft in drafts:
            if draft.kind not in PARSER_KINDS:
                raise IceSessionValidationError(
                    f"parser kind must be public_skate or open_ice, got {draft.kind!r}"
                )
            validate_duration_minutes(duration_minutes(draft.starts_at_utc, draft.ends_at_utc))
            validate_prices(
                price_adult_minor=draft.price_adult_minor,
                price_child_minor=draft.price_child_minor,
                price_rental_minor=draft.price_rental_minor,
            )
            if not draft.currency_code or len(draft.currency_code) != 3:
                raise IceSessionValidationError("currency_code must be a 3-letter code")
            key = (draft.arena_id, draft.starts_at_utc)
            if key in seen_starts:
                raise IceSessionOverlapError("two slots share the same starts_at after merge")
            seen_starts.add(key)
            validated.append(draft)
        return validated
