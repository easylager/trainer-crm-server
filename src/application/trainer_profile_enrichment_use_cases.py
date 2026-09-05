"""
After the first real booking: a quiet series asking the trainer to optionally fill
tariffs and «что не входит» in the profile.

Onboarding v2 does not collect prices. Bookings and reminders already work with NULL
price_cents. This module never gates that path — it only sends a postcard, then stops
once any tariff exists.

Anchor: created_at of the first non-sandbox booking that is not cancelled/declined.
Steps: D+1, D+8, D+21. Largest-unfired, same as onboarding reactivation.
Cancel-on-progress: a price row appears (variant or trainer_services.price_cents).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import messages as msg
from src.infrastructure.db.models import (
    PROFILE_NUDGE_STEP_KEYS,
    PROFILE_NUDGE_STEPS_ORDERED,
    TRAINER_STATUS_DEACTIVATED,
    TrainerProfileNudge,
)


@dataclass(frozen=True, slots=True)
class DueProfileNudge:
    trainer_id: int
    trainer_telegram_id: int
    step: str
    days_offset: int
    days_since_first_booking: int


def _pick_due_step(
    *,
    days_since_first_booking: int,
    already_sent: frozenset[str],
) -> tuple[str, int] | None:
    eligible: list[tuple[str, int]] = [
        (step, offset)
        for step, offset in PROFILE_NUDGE_STEPS_ORDERED
        if offset <= days_since_first_booking and step not in already_sent
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda item: item[1])


def render_profile_enrichment_nudge_text(step: str) -> str:
    bodies = {
        "p1": msg.TRAINER_PROFILE_ENRICH_NUDGE_P1,
        "p8": msg.TRAINER_PROFILE_ENRICH_NUDGE_P8,
        "p21": msg.TRAINER_PROFILE_ENRICH_NUDGE_P21,
    }
    body = bodies.get(step)
    if body is None:
        raise ValueError(f"Unknown profile nudge step: {step!r}")
    return body


PROFILE_ENRICHMENT_MINIAPP_PATH = "/webapp/trainer-profile?task=prices&from=hub"


def profile_enrichment_webapp_url(base: str) -> str:
    """Mini App URL for D+1/8/21 price nudges — focused overlay, not the full form."""
    return f"{base.rstrip('/')}{PROFILE_ENRICHMENT_MINIAPP_PATH}"


async def _list_sent_steps_for_trainer(session: AsyncSession, trainer_id: int) -> frozenset[str]:
    result = await session.execute(
        text("SELECT step FROM trainer_profile_nudges WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    return frozenset(str(row[0]) for row in result.fetchall())


async def list_profile_enrichment_candidates(session: AsyncSession) -> list[dict[str, Any]]:
    """
    Telegram-linked trainers with a real booking and still no tariff anywhere.
    """
    result = await session.execute(
        text(
            """
            SELECT
                t.id,
                t.telegram_id,
                (
                    SELECT MIN(b.created_at)
                    FROM bookings b
                    WHERE b.trainer_id = t.id
                      AND NOT b.is_sandbox
                      AND b.status NOT IN ('cancelled', 'declined')
                ) AS first_booking_at
            FROM trainers t
            WHERE t.telegram_id IS NOT NULL
              AND t.status <> :deactivated
              AND EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.trainer_id = t.id
                      AND NOT b.is_sandbox
                      AND b.status NOT IN ('cancelled', 'declined')
              )
              AND NOT EXISTS (
                    SELECT 1 FROM trainer_service_price_variants v
                    WHERE v.trainer_id = t.id
              )
              AND NOT EXISTS (
                    SELECT 1 FROM trainer_services ts
                    WHERE ts.trainer_id = t.id
                      AND ts.price_cents IS NOT NULL
              )
            """
        ),
        {"deactivated": TRAINER_STATUS_DEACTIVATED},
    )
    out: list[dict[str, Any]] = []
    for row in result.fetchall():
        if row[2] is None:
            continue
        out.append(
            {
                "trainer_id": int(row[0]),
                "trainer_telegram_id": int(row[1]),
                "first_booking_at": row[2],
            }
        )
    return out


async def compute_due_profile_enrichment_nudges(
    session: AsyncSession, *, now: datetime | None = None
) -> list[DueProfileNudge]:
    moment = now or datetime.now(timezone.utc)
    due: list[DueProfileNudge] = []
    for cand in await list_profile_enrichment_candidates(session):
        first_at = cand["first_booking_at"]
        if first_at.tzinfo is None:
            first_at = first_at.replace(tzinfo=timezone.utc)
        days = max(0, int((moment - first_at).total_seconds() // 86400))
        sent = await _list_sent_steps_for_trainer(session, cand["trainer_id"])
        picked = _pick_due_step(days_since_first_booking=days, already_sent=sent)
        if picked is None:
            continue
        step_key, days_offset = picked
        due.append(
            DueProfileNudge(
                trainer_id=cand["trainer_id"],
                trainer_telegram_id=cand["trainer_telegram_id"],
                step=step_key,
                days_offset=days_offset,
                days_since_first_booking=days,
            )
        )
    return due


async def mark_profile_enrichment_nudge_sent(
    session: AsyncSession,
    *,
    trainer_id: int,
    step: str,
) -> bool:
    if step not in PROFILE_NUDGE_STEP_KEYS:
        raise ValueError(f"Unknown profile nudge step: {step!r}")
    stmt = (
        pg_insert(TrainerProfileNudge)
        .values(trainer_id=trainer_id, step=step)
        .on_conflict_do_nothing(index_elements=["trainer_id", "step"])
    )
    result = await session.execute(stmt)
    await session.commit()
    return bool(result.rowcount and result.rowcount > 0)


__all__ = [
    "DueProfileNudge",
    "compute_due_profile_enrichment_nudges",
    "list_profile_enrichment_candidates",
    "mark_profile_enrichment_nudge_sent",
    "profile_enrichment_webapp_url",
    "PROFILE_ENRICHMENT_MINIAPP_PATH",
    "render_profile_enrichment_nudge_text",
    "_pick_due_step",
]
