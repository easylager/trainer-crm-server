"""
The public catalog gate — one expression, one predicate, no duplicates.

Lives in ``shared`` because both layers need it: infrastructure repositories build the SQL,
application code checks already-loaded rows, and infrastructure must not import application.

Before TASK-140 the gate was ``status = 'active' AND is_catalog_visible = true`` written out
eleven times, in four different spellings (one of them ``COALESCE(is_catalog_visible, true)``,
which defaulted a missing flag to *visible* and contradicted the others). Adding a state meant
finding all eleven; a missed copy is invisible in review and only shows up as a trainer
appearing on a surface they should not.

The state constants live here too, so ``src.infrastructure.db.models`` and
``src.application.trainer_catalog_state`` agree without either importing the other.
"""
from __future__ import annotations

from typing import Any

CATALOG_STATE_DRAFT = "draft"
CATALOG_STATE_PENDING_REVIEW = "pending_review"
CATALOG_STATE_PUBLISHED = "published"
CATALOG_STATE_HIDDEN = "hidden"
CATALOG_STATE_PAUSED = "paused"
# «Нужны правки», not a permanent refusal — a hard reject is account-level deactivation.
CATALOG_STATE_NEEDS_REVISION = "needs_revision"

CATALOG_STATES = (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_NEEDS_REVISION,
)

# Reason stamped on a ``draft`` card when the trainer asked to be listed but the card is not
# complete enough to send to a moderator. It keeps the wish on record — the old boolean flag
# did that, and the hub still needs to know whom to help finish.
REASON_TRAINER_REQUESTED = "trainer_requested"

# States in which the trainer has asked to be in the catalog — opt-in intent, which is a
# different question from "is listed right now". Bare ``draft`` is the only state that means
# "never asked, or withdrew the request entirely".
CATALOG_STATES_OPTED_IN = (
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_NEEDS_REVISION,
)

CATALOG_ACTOR_TRAINER = "trainer"
CATALOG_ACTOR_MODERATOR = "moderator"
CATALOG_ACTOR_SYSTEM = "system"
CATALOG_ACTOR_STUDIO = "studio"
CATALOG_ACTOR_API = "api"

CATALOG_ACTOR_TYPES = (
    CATALOG_ACTOR_TRAINER,
    CATALOG_ACTOR_MODERATOR,
    CATALOG_ACTOR_SYSTEM,
    CATALOG_ACTOR_STUDIO,
    CATALOG_ACTOR_API,
)


def catalog_listed_sql(alias: str = "t") -> str:
    """
    SQL fragment for "this trainer is in the public catalog", for the given table alias.

    Use it everywhere instead of writing the comparison out — that is the whole point.
    """
    if not alias or not alias.replace("_", "").isalnum():
        raise ValueError(f"invalid SQL alias: {alias!r}")
    return f"{alias}.catalog_state = '{CATALOG_STATE_PUBLISHED}'"


# Default-alias form for the common case (``FROM trainers t``).
CATALOG_LISTED_SQL = catalog_listed_sql()


def trainer_is_listed(row: Any) -> bool:
    """True when an already-loaded trainer row is in the public catalog. Dict or object."""
    if row is None:
        return False
    state = (
        row.get("catalog_state")
        if isinstance(row, dict)
        else getattr(row, "catalog_state", None)
    )
    return (state or "").strip() == CATALOG_STATE_PUBLISHED


def trainer_opted_into_catalog(row: Any) -> bool:
    """
    True when the trainer has asked to be listed — regardless of whether they are right now.

    Replaces the old ``is_catalog_visible`` reads that meant intent rather than visibility
    (e.g. whether to queue them for moderation, or whether the admin queue should show them).
    """
    if row is None:
        return False
    state = (
        row.get("catalog_state")
        if isinstance(row, dict)
        else getattr(row, "catalog_state", None)
    )
    state = (state or "").strip()
    if state in CATALOG_STATES_OPTED_IN:
        return True
    reason = (
        row.get("catalog_state_reason")
        if isinstance(row, dict)
        else getattr(row, "catalog_state_reason", None)
    )
    return state == CATALOG_STATE_DRAFT and (reason or "").strip() == REASON_TRAINER_REQUESTED
