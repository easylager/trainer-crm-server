"""Fixed price tiers for trainer services (catalog + booking snapshot)."""

from __future__ import annotations

from typing import Literal

# Display order: Детский → Взрослый → 2 ребенка → 2 взрослых → Взрослый + ребенок
PRICE_TIER_CHILD = "child"
PRICE_TIER_ADULT = "adult"
PRICE_TIER_TWO_CHILDREN = "two_children"
PRICE_TIER_TWO_ADULTS = "two_adults"
PRICE_TIER_ADULT_AND_CHILD = "adult_and_child"

PriceTierKind = Literal[
    "child",
    "adult",
    "two_children",
    "two_adults",
    "adult_and_child",
]

PRICE_TIER_ORDER: tuple[str, ...] = (
    PRICE_TIER_CHILD,
    PRICE_TIER_ADULT,
    PRICE_TIER_TWO_CHILDREN,
    PRICE_TIER_TWO_ADULTS,
    PRICE_TIER_ADULT_AND_CHILD,
)

VALID_PRICE_TIER_KINDS: frozenset[str] = frozenset(PRICE_TIER_ORDER)

PRICE_TIER_LABEL_RU: dict[str, str] = {
    PRICE_TIER_CHILD: "Детский",
    PRICE_TIER_ADULT: "Взрослый",
    PRICE_TIER_TWO_CHILDREN: "2 ребенка",
    PRICE_TIER_TWO_ADULTS: "2 взрослых",
    PRICE_TIER_ADULT_AND_CHILD: "Взрослый + ребенок",
}


def normalize_price_tier_kind(value: str | None) -> PriceTierKind | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in VALID_PRICE_TIER_KINDS:
        return s  # type: ignore[return-value]
    return None


def price_tier_label_ru(kind: str | None) -> str | None:
    if not kind:
        return None
    return PRICE_TIER_LABEL_RU.get(kind, kind)


def price_tier_sort_key(kind: str) -> int:
    try:
        return PRICE_TIER_ORDER.index(kind)
    except ValueError:
        return 99


def sql_order_case_tier_kind(column: str = "tier_kind") -> str:
    """PostgreSQL CASE for stable ordering in SELECTs (same as PRICE_TIER_ORDER)."""
    return f"""CASE COALESCE({column}, '{PRICE_TIER_ADULT}')
        WHEN '{PRICE_TIER_CHILD}' THEN 0
        WHEN '{PRICE_TIER_ADULT}' THEN 1
        WHEN '{PRICE_TIER_TWO_CHILDREN}' THEN 2
        WHEN '{PRICE_TIER_TWO_ADULTS}' THEN 3
        WHEN '{PRICE_TIER_ADULT_AND_CHILD}' THEN 4
        ELSE 99
    END"""
