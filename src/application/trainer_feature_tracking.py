"""
Feature-adoption tracking (TASK-028): "did this trainer ever successfully use feature X?"

Answers a different question than the guidance-hint telemetry in ``trainer_hub_action_inbox``
(shown/clicked/dismissed): this module records *outcomes*, not *interactions* — "попробовал
и получилось", emitted once per trainer per feature at the point the action actually
succeeds on the server, never on a client click that might not lead anywhere (see
``trainer_client_invite_tracking.sql_trainer_has_real_booking`` for the analogous pattern
applied to bookings specifically).

Two of the eleven tracked features already have their own long-lived signal elsewhere
(``trainers.client_invite_link_first_copied_at`` for ``share_link``,
``trainer_profiles.first_booking_milestone_at`` for ``first_real_booking``) — those signals
are not removed or replaced. ``record_feature_first_use`` is called alongside them too, so
the admin "how many features touched" distribution has one uniform table to query instead
of reconciling several historical signals with different claim semantics.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import TrainerFeatureFirstUse
from src.shared.audit import ACTOR_API, audit_log

logger = logging.getLogger(__name__)

FEATURE_WEEKLY_TEMPLATE = "weekly_template"
FEATURE_SHARE_LINK = "share_link"
FEATURE_FIRST_REAL_BOOKING = "first_real_booking"
FEATURE_PASS_PRODUCT_CREATED = "pass_product_created"
FEATURE_PASS_ISSUED = "pass_issued"
FEATURE_CERTIFICATE_ISSUED = "certificate_issued"
FEATURE_GROUP_CREATED = "group_created"
FEATURE_RECURRING_SET = "recurring_set"
FEATURE_CLIENT_NOTE_WRITTEN = "client_note_written"
FEATURE_STATS_OPENED = "stats_opened"
FEATURE_CATALOG_ENABLED = "catalog_enabled"

FEATURE_KEYS: frozenset[str] = frozenset(
    {
        FEATURE_WEEKLY_TEMPLATE,
        FEATURE_SHARE_LINK,
        FEATURE_FIRST_REAL_BOOKING,
        FEATURE_PASS_PRODUCT_CREATED,
        FEATURE_PASS_ISSUED,
        FEATURE_CERTIFICATE_ISSUED,
        FEATURE_GROUP_CREATED,
        FEATURE_RECURRING_SET,
        FEATURE_CLIENT_NOTE_WRITTEN,
        FEATURE_STATS_OPENED,
        FEATURE_CATALOG_ENABLED,
    }
)


async def record_feature_first_use(session: AsyncSession, trainer_id: int, feature: str) -> bool:
    """
    Idempotent: claims (trainer_id, feature) at most once, ever. Returns True the one time
    it actually claims the row (caller must commit then); False on every later call for the
    same pair — a plain, expected no-op, not an error — and also False (never raises) if the
    write itself fails for any reason.

    Emits ``trainer.feature_first_use`` only on the claiming call — repeat usage of a
    feature the trainer already has does not re-fire the event.

    This is guidance telemetry, never load-bearing: a caller like ``issue_pass_to_client``
    must still succeed even if this call can't (TASK-028 AC-007). The insert runs inside a
    SAVEPOINT so a failure here rolls back only this call, not the caller's whole
    transaction — a plain try/except around the statement would leave a shared asyncpg
    transaction aborted and doom the caller's later COMMIT too.
    """
    if feature not in FEATURE_KEYS:
        raise ValueError(f"Unknown feature key: {feature!r}")
    stmt = (
        pg_insert(TrainerFeatureFirstUse)
        .values(trainer_id=trainer_id, feature=feature)
        .on_conflict_do_nothing(index_elements=["trainer_id", "feature"])
    )
    try:
        async with session.begin_nested():
            result = await session.execute(stmt)
            claimed = bool(result.rowcount and result.rowcount > 0)
    except Exception:
        logger.exception(
            "record_feature_first_use failed trainer_id=%s feature=%s", trainer_id, feature
        )
        return False
    if claimed:
        audit_log(
            "trainer.feature_first_use",
            ACTOR_API,
            trainer_id,
            {"trainer_id": trainer_id, "feature": feature},
        )
    return claimed


async def count_features_touched(session: AsyncSession, trainer_id: int) -> int:
    """How many distinct features this trainer has ever claimed — for admin distributions."""
    r = await session.execute(
        text(
            "SELECT COUNT(*)::int FROM trainer_feature_first_use WHERE trainer_id = :tid"
        ),
        {"tid": trainer_id},
    )
    return int(r.scalar() or 0)


__all__ = [
    "FEATURE_KEYS",
    "FEATURE_WEEKLY_TEMPLATE",
    "FEATURE_SHARE_LINK",
    "FEATURE_FIRST_REAL_BOOKING",
    "FEATURE_PASS_PRODUCT_CREATED",
    "FEATURE_PASS_ISSUED",
    "FEATURE_CERTIFICATE_ISSUED",
    "FEATURE_GROUP_CREATED",
    "FEATURE_RECURRING_SET",
    "FEATURE_CLIENT_NOTE_WRITTEN",
    "FEATURE_STATS_OPENED",
    "FEATURE_CATALOG_ENABLED",
    "record_feature_first_use",
    "count_features_touched",
]
