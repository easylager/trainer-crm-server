"""
Catalog publication state for collectives (schools) — TASK-141 S5.

Parallel to ``src.application.trainer_catalog_state``, not built on it: schools self-publish
once the profile checklist clears (owner decision — no moderator queue), so this is a
3-state model (draft/published/hidden) without the moderation states, notification hook, or
actor set the trainer machine carries.

``set_collective_catalog_state`` is the only writer of ``collectives.catalog_state`` — same
discipline as the trainer module, so the journal in ``collective_catalog_events`` never
drifts from the column.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

COLLECTIVE_CATALOG_STATE_DRAFT = "draft"
COLLECTIVE_CATALOG_STATE_PUBLISHED = "published"
COLLECTIVE_CATALOG_STATE_HIDDEN = "hidden"

COLLECTIVE_CATALOG_STATES = (
    COLLECTIVE_CATALOG_STATE_DRAFT,
    COLLECTIVE_CATALOG_STATE_PUBLISHED,
    COLLECTIVE_CATALOG_STATE_HIDDEN,
)

COLLECTIVE_CATALOG_ACTOR_OPERATOR = "operator"
COLLECTIVE_CATALOG_ACTOR_SYSTEM = "system"
COLLECTIVE_CATALOG_ACTOR_TYPES = (
    COLLECTIVE_CATALOG_ACTOR_OPERATOR,
    COLLECTIVE_CATALOG_ACTOR_SYSTEM,
)

REASON_OPERATOR_PUBLISHED = "operator_published"
REASON_OPERATOR_HIDDEN = "operator_hidden"
# Written once by migration 0209, never by this module — see its docstring. Its
# ``reason_detail`` is a note to us, not a sentence for the operator; the screen must not
# read it back as the explanation of the current state.
REASON_BACKFILL_0209 = "backfill_0209"

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    COLLECTIVE_CATALOG_STATE_DRAFT: frozenset({COLLECTIVE_CATALOG_STATE_PUBLISHED}),
    COLLECTIVE_CATALOG_STATE_PUBLISHED: frozenset({COLLECTIVE_CATALOG_STATE_HIDDEN}),
    COLLECTIVE_CATALOG_STATE_HIDDEN: frozenset({COLLECTIVE_CATALOG_STATE_PUBLISHED}),
}


class CollectiveCatalogStateError(Exception):
    """Base for refusals raised by this module."""


class CollectiveCatalogStateTransitionError(CollectiveCatalogStateError):
    """The requested transition is not part of the state machine."""


async def get_collective_catalog_state(
    session: AsyncSession, collective_id: int
) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            """
            SELECT catalog_state, catalog_state_reason, catalog_state_changed_at
            FROM collectives WHERE id = :cid
            """
        ),
        {"cid": int(collective_id)},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "catalog_state": (row[0] or "").strip() or COLLECTIVE_CATALOG_STATE_DRAFT,
        "catalog_state_reason": row[1],
        "catalog_state_changed_at": row[2],
    }


async def list_collective_catalog_events(
    session: AsyncSession, collective_id: int, *, limit: int = 20
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(
            """
            SELECT from_state, to_state, reason, reason_detail, actor_type, actor_id, created_at
            FROM collective_catalog_events
            WHERE collective_id = :cid
            ORDER BY created_at DESC, id DESC
            LIMIT :lim
            """
        ),
        {"cid": int(collective_id), "lim": int(limit)},
    )
    return [
        {
            "from_state": row[0],
            "to_state": row[1],
            "reason": row[2],
            "reason_detail": row[3],
            "actor_type": row[4],
            "actor_id": row[5],
            "created_at": row[6],
        }
        for row in result.fetchall()
    ]


async def set_collective_catalog_state(
    session: AsyncSession,
    collective_id: int,
    state: str,
    *,
    reason: str | None = None,
    reason_detail: str | None = None,
    actor_type: str,
    actor_id: str | int | None = None,
) -> bool:
    """Move the school's catalog card to ``state``, journalling in the same transaction.

    Returns True when the state actually changed, False on a no-op (same state) or a
    missing collective. Raises ``CollectiveCatalogStateTransitionError`` for a transition
    outside the state machine.
    """
    if state not in COLLECTIVE_CATALOG_STATES:
        raise CollectiveCatalogStateError(f"unknown catalog state: {state!r}")
    if actor_type not in COLLECTIVE_CATALOG_ACTOR_TYPES:
        raise CollectiveCatalogStateError(f"unknown actor type: {actor_type!r}")

    current = await get_collective_catalog_state(session, collective_id)
    if current is None:
        logger.warning("set_collective_catalog_state: collective %s not found", collective_id)
        return False

    from_state = current["catalog_state"]
    if from_state == state:
        return False

    allowed = _ALLOWED_TRANSITIONS.get(from_state, frozenset())
    if state not in allowed:
        raise CollectiveCatalogStateTransitionError(
            f"collective catalog transition {from_state} → {state} is not allowed "
            f"(collective_id={collective_id})"
        )

    await session.execute(
        text(
            """
            UPDATE collectives SET
                catalog_state = :state,
                catalog_state_reason = :reason,
                catalog_state_changed_at = now()
            WHERE id = :cid
            """
        ),
        {"cid": int(collective_id), "state": state, "reason": reason},
    )
    await session.execute(
        text(
            """
            INSERT INTO collective_catalog_events (
                collective_id, from_state, to_state, reason, reason_detail, actor_type, actor_id
            ) VALUES (
                :cid, :from_state, :to_state, :reason, :reason_detail, :actor_type, :actor_id
            )
            """
        ),
        {
            "cid": int(collective_id),
            "from_state": from_state,
            "to_state": state,
            "reason": reason,
            "reason_detail": reason_detail,
            "actor_type": actor_type,
            "actor_id": str(actor_id) if actor_id is not None else None,
        },
    )
    await session.commit()
    logger.info(
        "collective_catalog_state %s → %s collective_id=%s reason=%s actor=%s",
        from_state,
        state,
        collective_id,
        reason,
        actor_type,
    )
    return True
