"""
TASK-029: server-side «Не сейчас» for hub rhythm hints.

Only a fixed allowlist of non-urgent hint ids may be snoozed here — the catalog invite
(``STEP_CATALOG_INVITE`` / ``catalog_publication``) already has its own mechanism
(``trainer_profiles.catalog_invite_dismissed_at``, ``POST /trainer/onboarding/next-step/dismiss``)
and is deliberately not touched (DEC-003 in TASK-029). Urgent hints (``open_loop_no_next``,
``slots_this_week`` — work that blocks a real client waiting on the trainer) are excluded on
principle (DEC-002/DEC-004): hiding them would let a trainer bury a real problem, not just
mute noise.

The snooze duration is a server decision, not a client one — the client never sends a
duration, only a ``hint_id``. This mirrors the "growth" (3 days) / "long" (10 days) split
that used to live only in ``trainer-home-main.js``'s ``dismissHubInboxRhythmItem``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import TrainerHintDismissal

# hint_id -> snooze days. Matches the "growth" (3d) / "long" (10d) split from the old
# client-only dismissHubInboxRhythmItem — same product intent, now server-owned.
DISMISSIBLE_HINT_DEFAULT_SNOOZE_DAYS: dict[str, int] = {
    "referral_growth": 3,
    "open_loop_free_next": 3,
    "slots_next_week": 3,
    "template": 10,
    "client_notes": 10,
    "open_loop_no_telegram": 10,
}

DISMISSIBLE_HINT_IDS: frozenset[str] = frozenset(DISMISSIBLE_HINT_DEFAULT_SNOOZE_DAYS)

# Always urgent — never dismissible, on either client or server (DEC-002/DEC-004).
NON_DISMISSIBLE_URGENT_HINT_IDS: frozenset[str] = frozenset({"open_loop_no_next", "slots_this_week"})


async def dismiss_rhythm_hint(session: AsyncSession, trainer_id: int, hint_id: str) -> None:
    """
    Snooze ``hint_id`` for its default duration, starting now. Idempotent-by-upsert: a repeat
    dismissal of the same (already-returned) hint simply pushes ``snooze_until`` forward again.

    Raises ``ValueError`` for anything outside ``DISMISSIBLE_HINT_IDS`` — including the two
    always-urgent ids and any unknown string. Caller (the API route) turns that into a 422.
    """
    if hint_id not in DISMISSIBLE_HINT_IDS:
        raise ValueError(f"Hint cannot be dismissed: {hint_id!r}")
    days = DISMISSIBLE_HINT_DEFAULT_SNOOZE_DAYS[hint_id]
    snooze_until = datetime.now(timezone.utc) + timedelta(days=days)
    stmt = (
        pg_insert(TrainerHintDismissal)
        .values(trainer_id=trainer_id, hint_id=hint_id, snooze_until=snooze_until)
        .on_conflict_do_update(
            index_elements=["trainer_id", "hint_id"],
            set_={"dismissed_at": text("now()"), "snooze_until": snooze_until},
        )
    )
    await session.execute(stmt)
    await session.commit()


async def clear_hint_snoozes(session: AsyncSession, trainer_id: int, hint_ids: list[str]) -> None:
    """
    Drop snooze rows for the given ids — used after the trainer saves new slots, so a stale
    «не сейчас» on a slots-related hint doesn't survive the change that made it relevant again
    (mirrors the client's old reset-on-save behavior).
    """
    if not hint_ids:
        return
    await session.execute(
        text(
            "DELETE FROM trainer_hint_dismissals WHERE trainer_id = :tid AND hint_id = ANY(:ids)"
        ),
        {"tid": trainer_id, "ids": list(hint_ids)},
    )
    await session.commit()


async def get_active_snoozes(session: AsyncSession, trainer_id: int) -> dict[str, datetime]:
    """``{hint_id: snooze_until}`` for currently-active snoozes only (``snooze_until > now()``)."""
    r = await session.execute(
        text(
            """
            SELECT hint_id, snooze_until FROM trainer_hint_dismissals
            WHERE trainer_id = :tid AND snooze_until IS NOT NULL AND snooze_until > now()
            """
        ),
        {"tid": trainer_id},
    )
    return {row[0]: row[1] for row in r.fetchall()}


__all__ = [
    "DISMISSIBLE_HINT_DEFAULT_SNOOZE_DAYS",
    "DISMISSIBLE_HINT_IDS",
    "NON_DISMISSIBLE_URGENT_HINT_IDS",
    "dismiss_rhythm_hint",
    "clear_hint_snoozes",
    "get_active_snoozes",
]
