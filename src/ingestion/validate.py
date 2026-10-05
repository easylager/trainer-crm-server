"""Validate CanonicalSlotDraft before any publisher (TASK-061) may persist."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.application.ice_session_use_cases import (
    IceSessionDurationError,
    IceSessionValidationError,
    duration_minutes,
    validate_duration_minutes,
    validate_prices,
)
from src.ingestion.types import PARSER_KINDS, CanonicalSlotDraft


@dataclass
class IceSessionValidationOutcome:
    validated: list[CanonicalSlotDraft] = field(default_factory=list)
    slots_dropped: int = 0
    drop_reasons: list[str] = field(default_factory=list)


class IceSessionValidator:
    def validate(
        self,
        drafts: list[CanonicalSlotDraft],
        *,
        max_drop_ratio: float = 1.0,
    ) -> list[CanonicalSlotDraft]:
        return self.validate_outcome(drafts, max_drop_ratio=max_drop_ratio).validated

    def validate_outcome(
        self,
        drafts: list[CanonicalSlotDraft],
        *,
        max_drop_ratio: float = 1.0,
    ) -> IceSessionValidationOutcome:
        seen_starts: set[tuple[int, object]] = set()
        validated: list[CanonicalSlotDraft] = []
        drop_reasons: list[str] = []
        for draft in drafts:
            reason = self._reject_reason(draft, seen_starts)
            if reason:
                drop_reasons.append(reason)
                continue
            key = (draft.arena_id, draft.starts_at_utc)
            seen_starts.add(key)
            validated.append(draft)
        dropped = len(drop_reasons)
        total = len(drafts)
        if total == 0:
            return IceSessionValidationOutcome(
                validated=validated,
                slots_dropped=0,
                drop_reasons=drop_reasons,
            )
        if not validated:
            raise IceSessionValidationError("no valid slots after validation")
        if total and dropped / total > max_drop_ratio:
            raise IceSessionValidationError(
                f"too many invalid slots: dropped {dropped} of {total}"
            )
        return IceSessionValidationOutcome(
            validated=validated,
            slots_dropped=dropped,
            drop_reasons=drop_reasons,
        )

    @staticmethod
    def _reject_reason(draft: CanonicalSlotDraft, seen_starts: set[tuple[int, object]]) -> str | None:
        if draft.kind not in PARSER_KINDS:
            return f"kind:{draft.kind!r}"
        try:
            validate_duration_minutes(duration_minutes(draft.starts_at_utc, draft.ends_at_utc))
            validate_prices(
                price_adult_minor=draft.price_adult_minor,
                price_child_minor=draft.price_child_minor,
                price_rental_minor=draft.price_rental_minor,
            )
        except (IceSessionDurationError, IceSessionValidationError) as exc:
            return str(exc)
        if not draft.currency_code or len(draft.currency_code) != 3:
            return "currency_code"
        key = (draft.arena_id, draft.starts_at_utc)
        if key in seen_starts:
            return "duplicate_start"
        return None
