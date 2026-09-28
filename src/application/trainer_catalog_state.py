"""
Catalog publication state — the single source of truth for "is this trainer listed?".

Before TASK-140 the answer was the pair ``status = 'active' AND is_catalog_visible = true``,
duplicated across eleven queries, and an incomplete profile silently demoted the whole
**account** to ``pending_profile``. So "card left the catalog" and "account never passed
moderation" were one event, with no notification attached to either, and the only way back
was for the trainer to reopen the profile screen and press Save.

This module owns the state and its journal:

* ``set_catalog_state`` is the **only** writer of ``trainers.catalog_state``. It updates the
  column, writes a ``trainer_catalog_events`` row and fires the trainer notification in one
  transaction. A test greps ``src/`` to keep it that way.
* ``CATALOG_LISTED_SQL`` / ``trainer_is_listed`` are the only gate the public catalog reads,
  replacing the eleven copies of the old pair.

``trainers.is_catalog_visible`` is kept for one release as a derived mirror so admin tooling
and analytics keep working; it is written here and nowhere else.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_profile_completeness import missing_labels_ru
from src.infrastructure.db.models import TRAINER_STATUS_DEACTIVATED
from src.shared.catalog_visibility import (
    CATALOG_ACTOR_API,
    CATALOG_ACTOR_MODERATOR,
    CATALOG_ACTOR_STUDIO,
    CATALOG_ACTOR_SYSTEM,
    CATALOG_ACTOR_TRAINER,
    CATALOG_ACTOR_TYPES,
    CATALOG_LISTED_SQL,
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_NEEDS_REVISION,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
    CATALOG_STATES,
    REASON_TRAINER_REQUESTED,
    catalog_listed_sql,
    trainer_is_listed,
    trainer_opted_into_catalog,
)

logger = logging.getLogger(__name__)

__all__ = [
    # Re-exported so callers take actor constants from the module that owns transitions.
    "CATALOG_ACTOR_API",
    "CATALOG_ACTOR_MODERATOR",
    "CATALOG_ACTOR_STUDIO",
    "CATALOG_ACTOR_SYSTEM",
    "CATALOG_ACTOR_TRAINER",
    "CATALOG_LISTED_SQL",
    "CatalogStateError",
    "CatalogStateTransitionError",
    "REASON_ACCOUNT_DEACTIVATED",
    "REASON_ACCOUNT_STATUS_CHANGED",
    "REASON_API_VISIBILITY_PATCH",
    "REASON_BACKFILL_0206",
    "REASON_AUTO_RESTORED",
    "REASON_MISSING_FIELDS",
    "REASON_MODERATOR_APPROVED",
    "REASON_MODERATOR_REVISION",
    "REASON_STUDIO_HIDDEN",
    "REASON_STUDIO_PUBLISHED",
    "REASON_TRAINER_CANCELLED",
    "REASON_TRAINER_HIDDEN",
    "REASON_TRAINER_REQUESTED",
    "REASON_TRAINER_RESTORED",
    "REASON_TRAINER_SUBMITTED",
    "catalog_listed_sql",
    "get_catalog_state",
    "list_catalog_events",
    "missing_fields_reason_detail",
    "set_catalog_state",
    "trainer_is_listed",
    "trainer_opted_into_catalog",
]

# --- Reason codes -----------------------------------------------------------------------
# Machine-readable; the sentence the trainer reads travels in ``reason_detail``.
REASON_MISSING_FIELDS = "missing_fields"
REASON_AUTO_RESTORED = "auto_restored"
REASON_TRAINER_SUBMITTED = "trainer_submitted"
REASON_TRAINER_HIDDEN = "trainer_hidden"
REASON_TRAINER_RESTORED = "trainer_restored"
REASON_TRAINER_CANCELLED = "trainer_cancelled"
REASON_MODERATOR_APPROVED = "moderator_approved"
REASON_MODERATOR_REVISION = "moderator_revision"
REASON_ACCOUNT_DEACTIVATED = "account_deactivated"
REASON_ACCOUNT_STATUS_CHANGED = "account_status_changed"
REASON_API_VISIBILITY_PATCH = "api_visibility_patch"
REASON_STUDIO_PUBLISHED = "studio_published"
REASON_STUDIO_HIDDEN = "studio_hidden"
# Written once by migration 0206, never by this module. Its ``reason_detail`` is a note to us
# («восстановлено из status + is_catalog_visible»), not a sentence for the trainer — the screen
# must not read it back as the explanation of the current state.
REASON_BACKFILL_0206 = "backfill_0206"


class CatalogStateError(Exception):
    """Base for refusals raised by this module."""


class CatalogStateTransitionError(CatalogStateError):
    """The requested transition is not part of the state machine."""


# Allowed transitions. Deliberately strict: every writer goes through this function, so an
# unlisted edge is a bug in the caller rather than a case to tolerate silently.
#
# Two rules live outside the table: any state may go to ``draft`` (account deactivation), and
# a transition to the current state is a no-op rather than an error.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    CATALOG_STATE_DRAFT: frozenset({CATALOG_STATE_PENDING_REVIEW}),
    # `pending_review → paused` — анкета сломалась, пока карточка стояла в очереди. Ребра тут не
    # было, хотя ``reconcile_catalog_state_for_card`` именно этот переход и делает: тренер,
    # который стёр телефон, ожидая модератора, получал CatalogStateTransitionError прямо из
    # сохранения профиля. Состояние правильное — одобрять карточку с дырой нельзя, — а дорога
    # назад уже существует (`paused → pending_review`).
    CATALOG_STATE_PENDING_REVIEW: frozenset(
        {CATALOG_STATE_PUBLISHED, CATALOG_STATE_NEEDS_REVISION, CATALOG_STATE_PAUSED}
    ),
    # A moderator asking an *active* trainer for edits does not unpublish the card — it only
    # discards the pending revision. So `published → needs_revision` is intentionally absent.
    #
    # `published → pending_review` is for the account losing its approval: an admin moving the
    # status out of `active` takes the card back to the queue, where its content is intact and
    # only the approval is missing (see ``update_trainer_status``).
    CATALOG_STATE_PUBLISHED: frozenset(
        {CATALOG_STATE_HIDDEN, CATALOG_STATE_PAUSED, CATALOG_STATE_PENDING_REVIEW}
    ),
    CATALOG_STATE_HIDDEN: frozenset({CATALOG_STATE_PUBLISHED}),
    CATALOG_STATE_PAUSED: frozenset({CATALOG_STATE_PUBLISHED, CATALOG_STATE_PENDING_REVIEW}),
    CATALOG_STATE_NEEDS_REVISION: frozenset({CATALOG_STATE_PENDING_REVIEW}),
}


def missing_fields_reason_detail(missing: list[str]) -> str:
    """
    Human sentence for a ``paused`` card, built from submission-readiness field keys.

    Reuses the same Russian labels the profile screen shows, so the push and the screen never
    disagree about what is missing.
    """
    labels = missing_labels_ru(missing or [], first_name_only=True)
    if not labels:
        return "Карточка больше не отвечает требованиям каталога."
    if len(labels) == 1:
        return f"В карточке не хватает: {labels[0]}."
    return "В карточке не хватает: " + ", ".join(labels) + "."


async def get_catalog_state(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """Current state row (state, reason, changed_at, account status). None if trainer missing."""
    result = await session.execute(
        text(
            """
            SELECT catalog_state, catalog_state_reason, catalog_state_changed_at, status
            FROM trainers WHERE id = :tid
            """
        ),
        {"tid": int(trainer_id)},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "catalog_state": (row[0] or "").strip() or CATALOG_STATE_DRAFT,
        "catalog_state_reason": row[1],
        "catalog_state_changed_at": row[2],
        "trainer_status": (row[3] or "").strip(),
    }


async def list_catalog_events(
    session: AsyncSession, trainer_id: int, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Journal for the trainer-facing history block, newest first."""
    result = await session.execute(
        text(
            """
            SELECT from_state, to_state, reason, reason_detail, actor_type, actor_id, created_at
            FROM trainer_catalog_events
            WHERE trainer_id = :tid
            ORDER BY created_at DESC, id DESC
            LIMIT :lim
            """
        ),
        {"tid": int(trainer_id), "lim": int(limit)},
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


async def set_catalog_state(
    session: AsyncSession,
    trainer_id: int,
    state: str,
    *,
    reason: str | None = None,
    reason_detail: str | None = None,
    actor_type: str,
    actor_id: str | int | None = None,
    notify: bool = True,
) -> bool:
    """
    Move the trainer's catalog card to ``state``, journalling and notifying.

    The only writer of ``trainers.catalog_state``. Returns True when the state actually
    changed, False on a no-op (same state, same reason) or a missing trainer.

    Raises ``CatalogStateTransitionError`` for a transition outside the state machine, and
    ``CatalogStateError`` when publishing a deactivated account — a card must never outlive
    the account it belongs to.

    ``notify=False`` is for flows that already tell the trainer in the same breath (migration
    backfill, a screen the trainer is looking at) — never to make a silent removal convenient.
    """
    if state not in CATALOG_STATES:
        raise CatalogStateError(f"unknown catalog state: {state!r}")
    if actor_type not in CATALOG_ACTOR_TYPES:
        raise CatalogStateError(f"unknown actor type: {actor_type!r}")

    current = await get_catalog_state(session, trainer_id)
    if current is None:
        logger.warning("set_catalog_state: trainer %s not found", trainer_id)
        return False

    from_state = current["catalog_state"]
    if state == CATALOG_STATE_PUBLISHED and current["trainer_status"] == TRAINER_STATUS_DEACTIVATED:
        raise CatalogStateError(
            f"cannot publish catalog card of a deactivated account (trainer_id={trainer_id})"
        )

    if from_state == state and (current["catalog_state_reason"] or None) == (reason or None):
        return False

    if from_state != state and state != CATALOG_STATE_DRAFT:
        allowed = _ALLOWED_TRANSITIONS.get(from_state, frozenset())
        if state not in allowed:
            raise CatalogStateTransitionError(
                f"catalog transition {from_state} → {state} is not allowed "
                f"(trainer_id={trainer_id})"
            )

    await session.execute(
        text(
            """
            UPDATE trainers SET
                catalog_state = :state,
                catalog_state_reason = :reason,
                catalog_state_changed_at = now(),
                is_catalog_visible = :visible
            WHERE id = :tid
            """
        ),
        {
            "tid": int(trainer_id),
            "state": state,
            "reason": reason,
            "visible": state == CATALOG_STATE_PUBLISHED,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO trainer_catalog_events (
                trainer_id, from_state, to_state, reason, reason_detail, actor_type, actor_id
            ) VALUES (
                :tid, :from_state, :to_state, :reason, :reason_detail, :actor_type, :actor_id
            )
            """
        ),
        {
            "tid": int(trainer_id),
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
        "catalog_state %s → %s trainer_id=%s reason=%s actor=%s",
        from_state,
        state,
        trainer_id,
        reason,
        actor_type,
    )

    if notify:
        from src.application.trainer_catalog_notify import notify_catalog_state_change

        try:
            await notify_catalog_state_change(
                session,
                trainer_id,
                from_state=from_state,
                to_state=state,
                reason=reason,
                reason_detail=reason_detail,
            )
        except Exception:  # noqa: BLE001 — a failed push must not roll back the transition
            logger.exception(
                "catalog state notification failed trainer_id=%s state=%s", trainer_id, state
            )
    return True
