"""Validate CanonicalSlotDraft before any publisher (TASK-061) may persist.

TASK-187: построчно. Плохая строка отбрасывается с причиной, прогон падает, только
если отброшено всё или больше ``max_invalid_slot_ratio`` (конфиг job, по умолчанию
``DEFAULT_MAX_INVALID_SLOT_RATIO``). Раньше одна кривая строка роняла весь прогон,
и арена застывала на старых данных.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.application.ice_session_use_cases import (
    IceSessionDurationError,
    IceSessionValidationError,
    duration_minutes,
    validate_duration_minutes,
    validate_prices,
)
from src.ingestion.types import PARSER_KINDS, CanonicalSlotDraft

logger = logging.getLogger(__name__)

#: Доля отброшенных строк, выше которой прогон считается сломанным (вёрстка уехала):
#: публиковать половину расписания хуже, чем оставить прошлое и поднять алерт.
DEFAULT_MAX_INVALID_SLOT_RATIO = 0.5

DROP_KIND = "вид"
DROP_DURATION = "длительность"
DROP_PRICE = "цена"
DROP_CURRENCY = "валюта"
DROP_DUPLICATE = "дубль начала"


def max_invalid_slot_ratio(config: Mapping[str, Any] | None) -> float:
    """``max_invalid_slot_ratio`` из конфига job; мусор в конфиге → дефолт, а не исключение."""
    raw = (config or {}).get("max_invalid_slot_ratio")
    if raw is None or isinstance(raw, bool):
        return DEFAULT_MAX_INVALID_SLOT_RATIO
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("bad max_invalid_slot_ratio=%r in job config; using default", raw)
        return DEFAULT_MAX_INVALID_SLOT_RATIO
    if not math.isfinite(value):
        return DEFAULT_MAX_INVALID_SLOT_RATIO
    return min(1.0, max(0.0, value))


@dataclass
class IceSessionValidationOutcome:
    validated: list[CanonicalSlotDraft] = field(default_factory=list)
    slots_dropped: int = 0
    drop_reasons: list[str] = field(default_factory=list)

    def reason_counts(self) -> dict[str, int]:
        return dict(Counter(self.drop_reasons))


def _reasons_text(reasons: list[str]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(Counter(reasons).items()))


class IceSessionValidator:
    def validate(
        self,
        drafts: list[CanonicalSlotDraft],
        *,
        max_drop_ratio: float = DEFAULT_MAX_INVALID_SLOT_RATIO,
    ) -> list[CanonicalSlotDraft]:
        return self.validate_outcome(drafts, max_drop_ratio=max_drop_ratio).validated

    def validate_outcome(
        self,
        drafts: list[CanonicalSlotDraft],
        *,
        max_drop_ratio: float = DEFAULT_MAX_INVALID_SLOT_RATIO,
    ) -> IceSessionValidationOutcome:
        seen_starts: set[tuple[int, object]] = set()
        validated: list[CanonicalSlotDraft] = []
        drop_reasons: list[str] = []
        for draft in drafts:
            reason = self._reject_reason(draft, seen_starts)
            if reason:
                drop_reasons.append(reason)
                continue
            seen_starts.add((draft.arena_id, draft.starts_at_utc))
            validated.append(draft)
        dropped = len(drop_reasons)
        total = len(drafts)
        if total == 0:
            # Пустая выдача — не ошибка валидации: планировщик сам решит empty_source / empty_after_filter.
            return IceSessionValidationOutcome()
        if not validated:
            raise IceSessionValidationError(
                f"все {total} строк отброшены: {_reasons_text(drop_reasons)}"
            )
        if dropped / total > max_drop_ratio:
            raise IceSessionValidationError(
                f"отброшено {dropped} из {total} строк (порог {max_drop_ratio:.0%}): "
                f"{_reasons_text(drop_reasons)}"
            )
        return IceSessionValidationOutcome(
            validated=validated,
            slots_dropped=dropped,
            drop_reasons=drop_reasons,
        )

    @staticmethod
    def _reject_reason(draft: CanonicalSlotDraft, seen_starts: set[tuple[int, object]]) -> str | None:
        if draft.kind not in PARSER_KINDS:
            return DROP_KIND
        try:
            validate_duration_minutes(duration_minutes(draft.starts_at_utc, draft.ends_at_utc))
        except IceSessionDurationError:
            return DROP_DURATION
        try:
            validate_prices(
                price_adult_minor=draft.price_adult_minor,
                price_child_minor=draft.price_child_minor,
                price_rental_minor=draft.price_rental_minor,
            )
        except IceSessionValidationError:
            return DROP_PRICE
        if not draft.currency_code or len(draft.currency_code) != 3:
            return DROP_CURRENCY
        if (draft.arena_id, draft.starts_at_utc) in seen_starts:
            return DROP_DUPLICATE
        return None
