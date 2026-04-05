"""
Trainer onboarding checklist: profile completeness, future slots (any status in horizon), any booking.
Used by GET /api/webapp/trainer/onboarding/checklist (trainer hub + profile flows).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_use_cases import get_trainer, get_trainer_moderation_readiness
from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE

# How far ahead to look for slots (matches product: "reasonable horizon").
_SLOT_HORIZON_DAYS = 56

# Inline: inactive trainers cannot use schedule API; explain in Mini App.
_SLOTS_BOOKINGS_LOCKED_RU = (
    "Станет доступно после активации аккаунта: тогда откроются расписание и записи."
)


async def get_trainer_onboarding_checklist(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """Aggregated checklist flags; None if trainer row missing."""
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        return None
    st = (trainer.get("status") or "").strip()
    is_active = st == TRAINER_STATUS_ACTIVE

    readiness = await get_trainer_moderation_readiness(session, trainer_id)
    profile_complete = bool(readiness and readiness.get("complete"))

    out: dict[str, Any] = {
        "trainer_status": st,
        "is_active": is_active,
        "profile_complete": profile_complete,
        "has_future_available_slots": False,
        "has_future_slots": False,
        "has_any_booking": False,
        "slots_locked_reason": None,
        "bookings_locked_reason": None,
    }

    if not is_active:
        out["slots_locked_reason"] = _SLOTS_BOOKINGS_LOCKED_RU
        out["bookings_locked_reason"] = _SLOTS_BOOKINGS_LOCKED_RU
        return out

    today = date.today()
    horizon = today + timedelta(days=_SLOT_HORIZON_DAYS)
    r = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM slots
                WHERE trainer_id = :tid
                  AND slot_date >= :d0
                  AND slot_date <= :d1
                  AND status = 'available'
            )
            """
        ),
        {"tid": trainer_id, "d0": today, "d1": horizon},
    )
    out["has_future_available_slots"] = bool(r.scalar())

    # Onboarding step «слоты»: any concrete slot in horizon (free or already booked — not only «available»).
    r_slots = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM slots
                WHERE trainer_id = :tid
                  AND slot_date >= :d0
                  AND slot_date <= :d1
                  AND status IN ('available', 'booked')
            )
            """
        ),
        {"tid": trainer_id, "d0": today, "d1": horizon},
    )
    out["has_future_slots"] = bool(r_slots.scalar())

    r2 = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM bookings
                WHERE trainer_id = :tid
                  AND status NOT IN ('cancelled', 'declined')
            )
            """
        ),
        {"tid": trainer_id},
    )
    out["has_any_booking"] = bool(r2.scalar())
    return out
