"""
Lead Mode recovery: D+0..D+30 reactivation series.

This module is the *scheduler* — it decides which nudge step is due for which trainer at any given
moment, and records the send into an idempotency log. The actual delivery (Telegram bot send +
keyboard) lives in `notification_loops.py`; the message templates live in `messages.py`.

Design contract (see docs/plans/lead-mode-revenue-retention.md, Phase 5):

- Series steps: D+0 (welcome to Lead Mode), D+3 (gentle reminder), D+14 (loss framing), D+30 (last call).
- A trainer enters the series the moment they transition into LEAD_MODE (subscription expires + active
  status + catalog visible). The anchor for offsets is `last_subscription_expires_at`.
- Each step is delivered at most once per trainer (UNIQUE (trainer_id, step) in the recovery log).
- Cancel-on-payment is implicit: once the trainer leaves LEAD_MODE, this module stops listing them as
  candidates and remaining steps will never fire. No explicit cancel API is required.
- The loop runs once per day. At each tick it picks the *largest* step whose offset has elapsed and
  has not yet been sent — so a trainer who sat dormant for 20 days then we re-enable the loop will
  fast-forward to D+14 (skipping D+0/D+3 by design — those windows are for fresh churners only).
- "Largest unfired" is intentional: it keeps recovery messages fresh when the loop is delayed and
  prevents stale "your trial just ended" pings going out to month-old churn.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.demand_signals_use_cases import SignalsRecap, get_signals_since
from src.application.lifecycle_use_cases import (
    LifecycleSnapshot,
    LifecycleStage,
    resolve_lifecycle_snapshot,
)
from src.infrastructure.db.models import (
    RECOVERY_STEP_KEYS,
    RECOVERY_STEPS_ORDERED,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIAL,
    TRAINER_STATUS_ACTIVE,
    TrainerRecoveryNudge,
)


@dataclass(frozen=True, slots=True)
class DueRecoveryNudge:
    """One due nudge for one trainer — fully prepared for delivery (no DB side effects)."""

    trainer_id: int
    trainer_telegram_id: int
    step: str
    days_offset: int
    days_in_lead_mode: int
    last_expires_at: datetime
    signals: SignalsRecap

    def as_log_dict(self) -> dict[str, Any]:
        return {
            "trainer_id": self.trainer_id,
            "step": self.step,
            "days_offset": self.days_offset,
            "days_in_lead_mode": self.days_in_lead_mode,
        }


def _pick_due_step(
    *,
    days_in_lead_mode: int,
    already_sent: frozenset[str],
) -> tuple[str, int] | None:
    """Pure: pick the largest-offset step whose window has elapsed and which hasn't been sent yet.

    "Largest unfired" semantics:
        days=0  → fires d0 if not sent
        days=4, sent={d0}     → fires d3
        days=20, sent={}      → fires d14 directly (skips d0/d3 — see module docstring)
        days=40, sent={d0,d3,d14} → fires d30
        days=40, sent={d0,d3,d14,d30} → no nudge (series exhausted)
    """
    eligible: list[tuple[str, int]] = [
        (step, offset)
        for step, offset in RECOVERY_STEPS_ORDERED
        if offset <= days_in_lead_mode and step not in already_sent
    ]
    if not eligible:
        return None
    # Largest offset wins; ties are impossible because RECOVERY_STEPS_ORDERED has unique offsets.
    return max(eligible, key=lambda item: item[1])


async def _list_lead_mode_candidates(session: AsyncSession) -> list[dict[str, Any]]:
    """Trainers currently in LEAD_MODE shape (active status + visible + last expiry passed)."""
    now = datetime.now(timezone.utc)
    # Eligibility query: status=active, catalog visible, telegram set, no live subscription, and
    # there exists a most-recent expiry that has already passed. We resolve the actual stage via
    # `resolve_lifecycle_snapshot` per trainer afterwards to keep the SQL simple and the
    # invariant centralized.
    result = await session.execute(
        text(
            """
            SELECT
                t.id,
                t.telegram_id,
                (
                    SELECT MAX(ts.expires_at)
                    FROM trainer_subscriptions ts
                    WHERE ts.trainer_id = t.id
                ) AS last_expires_at
            FROM trainers t
            WHERE t.status = :status_active
              AND t.is_catalog_visible = TRUE
              AND t.telegram_id IS NOT NULL
              AND NOT EXISTS (
                    SELECT 1
                    FROM trainer_subscriptions ts
                    WHERE ts.trainer_id = t.id
                      AND ts.started_at <= :now
                      AND ts.expires_at > :now
                      AND ts.status IN (:s_trial, :s_active)
              )
            """
        ),
        {
            "status_active": TRAINER_STATUS_ACTIVE,
            "now": now,
            "s_trial": SUBSCRIPTION_STATUS_TRIAL,
            "s_active": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    rows = result.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        last_exp = row[2]
        if last_exp is None or last_exp >= now:
            # No prior subscription, or the "last" one is somehow in the future — not lead mode.
            continue
        out.append(
            {
                "trainer_id": int(row[0]),
                "trainer_telegram_id": int(row[1]),
                "last_expires_at": last_exp,
            }
        )
    return out


async def _list_sent_steps_for_trainer(
    session: AsyncSession, trainer_id: int
) -> frozenset[str]:
    result = await session.execute(
        text(
            "SELECT step FROM trainer_recovery_nudges WHERE trainer_id = :tid"
        ),
        {"tid": trainer_id},
    )
    return frozenset(str(row[0]) for row in result.fetchall())


async def compute_due_nudges(
    session: AsyncSession, *, now: datetime | None = None
) -> list[DueRecoveryNudge]:
    """
    Top-level scheduler: list every trainer whose next recovery step is due right now.

    Pure DB reads — no writes here. Caller (notification loop) sends + calls `mark_nudge_sent`.
    """
    moment = now or datetime.now(timezone.utc)
    candidates = await _list_lead_mode_candidates(session)
    if not candidates:
        return []

    # Sanity-check via the canonical lifecycle resolver so we never fire on edge cases the SQL
    # missed (e.g. unknown status values, race conditions). One extra round-trip per candidate is
    # acceptable: the lead-mode pool is tiny relative to the full trainer base.
    due: list[DueRecoveryNudge] = []
    for cand in candidates:
        snap: LifecycleSnapshot = await resolve_lifecycle_snapshot(session, cand["trainer_id"])
        if snap.stage != LifecycleStage.LEAD_MODE:
            continue
        last_exp: datetime = cand["last_expires_at"]
        if last_exp.tzinfo is None:
            last_exp = last_exp.replace(tzinfo=timezone.utc)
        days_in_lead_mode = max(0, int((moment - last_exp).total_seconds() // 86400))

        sent = await _list_sent_steps_for_trainer(session, cand["trainer_id"])
        picked = _pick_due_step(
            days_in_lead_mode=days_in_lead_mode, already_sent=sent
        )
        if picked is None:
            continue
        step_key, days_offset = picked

        signals = await get_signals_since(
            session,
            trainer_id=cand["trainer_id"],
            since=last_exp,
            now=moment,
        )
        due.append(
            DueRecoveryNudge(
                trainer_id=cand["trainer_id"],
                trainer_telegram_id=cand["trainer_telegram_id"],
                step=step_key,
                days_offset=days_offset,
                days_in_lead_mode=days_in_lead_mode,
                last_expires_at=last_exp,
                signals=signals,
            )
        )
    return due


async def mark_nudge_sent(
    session: AsyncSession,
    *,
    trainer_id: int,
    step: str,
    expires_at_anchor: datetime | None,
) -> bool:
    """
    Idempotent insert into trainer_recovery_nudges. Returns True if a new row was written, False if
    the (trainer, step) pair was already present (concurrent loop, replay, or restart).
    """
    if step not in RECOVERY_STEP_KEYS:
        raise ValueError(f"Unknown recovery step: {step!r}")
    stmt = (
        pg_insert(TrainerRecoveryNudge)
        .values(
            trainer_id=trainer_id,
            step=step,
            expires_at_anchor=expires_at_anchor,
        )
        .on_conflict_do_nothing(index_elements=["trainer_id", "step"])
    )
    result = await session.execute(stmt)
    await session.commit()
    return bool(result.rowcount and result.rowcount > 0)


__all__ = [
    "DueRecoveryNudge",
    "compute_due_nudges",
    "mark_nudge_sent",
    "_pick_due_step",  # exported for pure unit tests
]
