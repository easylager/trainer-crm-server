"""
Onboarding reactivation: D+1/D+3/D+7 nudge series for trainers who linked Telegram but stalled
before finishing onboarding.

This module is the *scheduler* — it decides which nudge step is due for which trainer at any given
moment, and records the send into an idempotency log. The actual delivery (Telegram bot send +
keyboard) lives in `notification_loops.py`; message templates live in `messages.py`.

Design contract (see .ai/tasks/TASK-011.md):

- Candidate segment: telegram-linked trainers who have not finished onboarding —
  (a) status == pending_profile, or (b) status == active with zero bookings ever (never got their
  first client — Care Pulse's dormant-client logic does not cover "never had a client" trainers).
  `pending_contract` / `pending_payment` are excluded — TASK-011 leaves that unresolved.
- Stage inside the segment is derived from `get_trainer_onboarding_checklist` +
  `get_trainer_moderation_readiness` — no new diagnostic SQL, reuses the existing checklist.
- Steps: D+1 (gentle nudge), D+3 (names the specific missing item), D+7 (last call before the
  trial quietly burns). Anchor is `trainers.created_at` — this equals the Telegram-link moment in
  practice because the legacy site-first creation path (`POST /api/trainers`) is gated by
  `legacy_trainers_api_enabled` (off in production); every real trainer is created via
  `consume_link_token`, where `created_at` and telegram_id are set together.
- Each step is delivered at most once per trainer (UNIQUE (trainer_id, step) in the idempotency log).
- Cancel-on-progress is implicit: once a trainer's stage resolves to None (finished the relevant
  step, or is waiting on admin review with nothing left to do), this module stops listing them as a
  candidate, and remaining steps never fire.
- "Largest unfired" semantics, same as Lead Mode recovery: a trainer who sat dormant for 10 days
  then gets a delayed tick fast-forwards to D+7 (skips D+1/D+3 by design).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_client_invite_tracking import sql_trainer_has_real_booking
from src.application.trainer_onboarding_checklist import get_trainer_onboarding_checklist
from src.application.trainer_use_cases import get_trainer, get_trainer_moderation_readiness
from src.infrastructure.db.models import (
    ONBOARDING_NUDGE_STEP_KEYS,
    ONBOARDING_NUDGE_STEPS_ORDERED,
    SUBSCRIPTION_STATUS_TRIAL,
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_PENDING_PROFILE,
    TrainerOnboardingNudge,
)

# When trial days-remaining is at or below this, the nudge escalates urgency in the copy (AC-004).
# Deliberately separate from `subscription_reminder_trial_days_ahead` (billing reminder, D-1 only) —
# this is an earlier, softer signal woven into the onboarding nudge itself.
TRIAL_URGENCY_THRESHOLD_DAYS = 3

# Stuck-stage ids — see TASK-011 AC-002. Ordered here by typical funnel position, not priority.
STAGE_EMPTY_FORM = "empty_form"
STAGE_MISSING_FIELD = "missing_field"
STAGE_REJECTED_RESUBMIT = "rejected_resubmit"
STAGE_NOT_SUBMITTED = "not_submitted"
STAGE_NO_BOOKING = "no_booking"


@dataclass(frozen=True, slots=True)
class OnboardingCandidate:
    """One telegram-linked trainer stalled in onboarding, with its stuck stage resolved."""

    trainer_id: int
    trainer_telegram_id: int
    created_at: datetime
    stage: str
    missing_labels_ru: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DueOnboardingNudge:
    """One due nudge for one trainer — fully prepared for delivery (no DB side effects)."""

    trainer_id: int
    trainer_telegram_id: int
    step: str
    days_offset: int
    days_since_start: int
    stage: str
    missing_labels_ru: tuple[str, ...]


def determine_onboarding_stage(
    *,
    trainer_status: str,
    tt_minimal_complete: bool,
    profile_complete: bool,
    moderation_submitted: bool,
    has_moderation_feedback: bool,
    has_real_booking: bool,
) -> str | None:
    """
    Pure: map checklist flags to a stuck-stage id, or None if the trainer is not actionable right
    now (fully onboarded, or waiting on admin review with nothing left for them to do).
    """
    # Первая настоящая запись — практика уже работает. Старая серия («добить анкету») здесь
    # умолкает: тарифы и «что не входит» — отдельный мягкий пинг после записи. Читаем
    # has_real_booking, а не has_any_booking (TASK-027) — иначе одна тестовая или мгновенно
    # отменённая запись молча гасит всю серию реактивации ровно тому, кому она нужнее всего.
    if has_real_booking:
        return None
    if trainer_status == TRAINER_STATUS_ACTIVE:
        return STAGE_NO_BOOKING
    if trainer_status != TRAINER_STATUS_PENDING_PROFILE:
        return None
    if not tt_minimal_complete:
        return STAGE_EMPTY_FORM
    if has_moderation_feedback and not moderation_submitted:
        return STAGE_REJECTED_RESUBMIT
    if not profile_complete:
        return STAGE_MISSING_FIELD
    if not moderation_submitted:
        return STAGE_NOT_SUBMITTED
    return None


def _pick_due_step(
    *,
    days_since_start: int,
    already_sent: frozenset[str],
) -> tuple[str, int] | None:
    """Pure: pick the largest-offset step whose window has elapsed and hasn't been sent yet."""
    eligible: list[tuple[str, int]] = [
        (step, offset)
        for step, offset in ONBOARDING_NUDGE_STEPS_ORDERED
        if offset <= days_since_start and step not in already_sent
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda item: item[1])


async def _list_segment_candidates(session: AsyncSession) -> list[dict[str, Any]]:
    """
    Telegram-linked trainers in the onboarding-reactivation segment (status shape only).

    The "no real booking yet" exclusion must match ``has_real_booking`` in the checklist
    (TASK-027) — a sandbox demo or an instantly-voided booking must not silence this whole
    series, and a real booking that was later cancelled must not resurrect a trainer into it.
    Both this SQL-level filter and ``determine_onboarding_stage``'s own gate below must read
    the same signal: if the SQL admits a candidate but the stage resolver still checks the
    old ``has_any_booking``, the trainer is silently dropped a second time.
    """
    result = await session.execute(
        text(
            f"""
            SELECT t.id, t.telegram_id, t.created_at
            FROM trainers t
            WHERE t.telegram_id IS NOT NULL
              AND t.status IN (:status_pending_profile, :status_active)
              AND NOT {sql_trainer_has_real_booking()}
            """
        ),
        {
            "status_pending_profile": TRAINER_STATUS_PENDING_PROFILE,
            "status_active": TRAINER_STATUS_ACTIVE,
        },
    )
    rows = result.fetchall()
    return [
        {"trainer_id": int(r[0]), "trainer_telegram_id": int(r[1]), "created_at": r[2]}
        for r in rows
    ]


async def _list_sent_steps_for_trainer(session: AsyncSession, trainer_id: int) -> frozenset[str]:
    result = await session.execute(
        text("SELECT step FROM trainer_onboarding_nudges WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    return frozenset(str(row[0]) for row in result.fetchall())


async def list_onboarding_candidates(session: AsyncSession) -> list[OnboardingCandidate]:
    """
    Resolve the segment's stuck stage for each trainer via the existing checklist/readiness data.
    One extra round-trip per candidate: acceptable at current trainer volume (see TASK-011 Risks —
    revisit with a bulk query if the pending-profile pool grows by orders of magnitude).
    """
    raw = await _list_segment_candidates(session)
    out: list[OnboardingCandidate] = []
    for cand in raw:
        checklist = await get_trainer_onboarding_checklist(session, cand["trainer_id"])
        if checklist is None:
            continue
        trainer = await get_trainer(session, cand["trainer_id"])
        readiness = await get_trainer_moderation_readiness(session, cand["trainer_id"])
        has_feedback = bool(trainer and str(trainer.get("moderation_feedback") or "").strip())
        stage = determine_onboarding_stage(
            trainer_status=checklist["trainer_status"],
            tt_minimal_complete=bool(checklist.get("tt_minimal_complete")),
            profile_complete=bool(checklist.get("profile_complete")),
            moderation_submitted=bool(checklist.get("moderation_submitted")),
            has_moderation_feedback=has_feedback,
            has_real_booking=bool(checklist.get("has_real_booking")),
        )
        if stage is None:
            continue
        labels: tuple[str, ...] = ()
        if readiness:
            if stage == STAGE_EMPTY_FORM:
                labels = tuple(readiness.get("tt_minimal_missing_labels_ru") or ())
            elif stage in (STAGE_MISSING_FIELD, STAGE_REJECTED_RESUBMIT):
                labels = tuple(readiness.get("missing_labels_ru") or ())
        out.append(
            OnboardingCandidate(
                trainer_id=cand["trainer_id"],
                trainer_telegram_id=cand["trainer_telegram_id"],
                created_at=cand["created_at"],
                stage=stage,
                missing_labels_ru=labels,
            )
        )
    return out


async def compute_due_onboarding_nudges(
    session: AsyncSession, *, now: datetime | None = None
) -> list[DueOnboardingNudge]:
    """Top-level scheduler: every trainer whose next onboarding-reactivation step is due now."""
    moment = now or datetime.now(timezone.utc)
    candidates = await list_onboarding_candidates(session)
    if not candidates:
        return []

    due: list[DueOnboardingNudge] = []
    for cand in candidates:
        created_at = cand.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        days_since_start = max(0, int((moment - created_at).total_seconds() // 86400))

        sent = await _list_sent_steps_for_trainer(session, cand.trainer_id)
        picked = _pick_due_step(days_since_start=days_since_start, already_sent=sent)
        if picked is None:
            continue
        step_key, days_offset = picked
        due.append(
            DueOnboardingNudge(
                trainer_id=cand.trainer_id,
                trainer_telegram_id=cand.trainer_telegram_id,
                step=step_key,
                days_offset=days_offset,
                days_since_start=days_since_start,
                stage=cand.stage,
                missing_labels_ru=cand.missing_labels_ru,
            )
        )
    return due


async def get_trial_days_remaining(
    session: AsyncSession, trainer_id: int, *, now: datetime | None = None
) -> int | None:
    """
    Days left on the trainer's trial (rounded up), or None if they have no live trial row.
    Feeds AC-004's urgency escalation — kept separate from the billing reminder loop.
    """
    moment = now or datetime.now(timezone.utc)
    result = await session.execute(
        text(
            """
            SELECT expires_at FROM trainer_subscriptions
            WHERE trainer_id = :tid AND status = :status_trial AND expires_at > :now
            ORDER BY expires_at DESC
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "status_trial": SUBSCRIPTION_STATUS_TRIAL, "now": moment},
    )
    row = result.fetchone()
    if not row or row[0] is None:
        return None
    expires_at: datetime = row[0]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    remaining_seconds = (expires_at - moment).total_seconds()
    if remaining_seconds <= 0:
        return 0
    return math.ceil(remaining_seconds / 86400)


async def mark_onboarding_nudge_sent(
    session: AsyncSession,
    *,
    trainer_id: int,
    step: str,
    stage_anchor: str | None,
) -> bool:
    """
    Idempotent insert into trainer_onboarding_nudges. Returns True if a new row was written, False
    if the (trainer, step) pair was already present (concurrent loop, replay, or restart).
    """
    if step not in ONBOARDING_NUDGE_STEP_KEYS:
        raise ValueError(f"Unknown onboarding nudge step: {step!r}")
    stmt = (
        pg_insert(TrainerOnboardingNudge)
        .values(trainer_id=trainer_id, step=step, stage_anchor=stage_anchor)
        .on_conflict_do_nothing(index_elements=["trainer_id", "step"])
    )
    result = await session.execute(stmt)
    await session.commit()
    return bool(result.rowcount and result.rowcount > 0)


__all__ = [
    "OnboardingCandidate",
    "DueOnboardingNudge",
    "STAGE_EMPTY_FORM",
    "STAGE_MISSING_FIELD",
    "STAGE_REJECTED_RESUBMIT",
    "STAGE_NOT_SUBMITTED",
    "STAGE_NO_BOOKING",
    "determine_onboarding_stage",
    "list_onboarding_candidates",
    "compute_due_onboarding_nudges",
    "get_trial_days_remaining",
    "mark_onboarding_nudge_sent",
    "TRIAL_URGENCY_THRESHOLD_DAYS",
    "_pick_due_step",
]
