"""
Trainer onboarding checklist: submission readiness, full-profile flag, future slots, booking flags.
``profile_complete`` = moderation submission tier (8 criteria); ``full_profile_complete`` = dossier (12).
``tt_minimal_complete`` = 7-field TTV gate (schedule/bookings in Mini App before activation).
``has_upcoming_booking`` mirrors hub upcoming list logic (pending/confirmed on future-ended slots).
``has_completed_booking`` = at least one booking with status ``completed`` (hub nudge: client notes).
``last_completed_booking_client_id`` = ``client_id`` of the latest completed row by ``bookings.id`` (deep link).
``schedule_unlocked`` mirrors Mini App access (active or pending TTV + CRM trial).
``weekly_template_count`` = rows in ``trainer_schedule_templates`` (hub nudge after onboarding complete).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.subscription_tier_use_cases import trainer_has_crm_access
from src.application.trainer_use_cases import get_trainer, get_trainer_moderation_readiness
from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE, TRAINER_STATUS_PENDING_PROFILE
from src.shared.notification_hours import NOTIFICATION_TZ
from src.shared.trainer_status import normalize_trainer_status_value

# How far ahead to look for slots (matches product: "reasonable horizon").
_SLOT_HORIZON_DAYS = 56

# Inline: profile not ready for TTV path and no CRM trial yet.
_SLOTS_BOOKINGS_LOCKED_RU = (
    "Станет доступно после активации аккаунта: тогда откроются расписание и записи."
)
_SLOTS_BOOKINGS_LOCKED_PENDING_RU = (
    "Заполните базовый профиль (имя, телефон, город, услуга, площадка, длительность и окно записи) — "
    "тогда откроется расписание и тестовые записи до активации."
)
_SQL_SLOT_END_TS = f"((s.slot_date + s.end_time) AT TIME ZONE '{NOTIFICATION_TZ}')"


async def get_trainer_onboarding_checklist(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """Aggregated checklist flags; None if trainer row missing."""
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        return None
    st = normalize_trainer_status_value(trainer.get("status"))
    is_active = st == TRAINER_STATUS_ACTIVE

    readiness = await get_trainer_moderation_readiness(session, trainer_id)
    profile_complete = bool(readiness and readiness.get("complete"))
    full_profile_complete = bool(readiness and readiness.get("full_profile_complete"))
    tt_minimal_complete = bool(readiness and readiness.get("tt_minimal_complete"))

    out: dict[str, Any] = {
        "trainer_status": st,
        "is_active": is_active,
        "profile_complete": profile_complete,
        "full_profile_complete": full_profile_complete,
        "tt_minimal_complete": tt_minimal_complete,
        "weekly_template_count": 0,
        "has_future_available_slots": False,
        "has_future_slots": False,
        "has_any_booking": False,
        "has_upcoming_booking": False,
        "has_confirmed_booking": False,
        "has_completed_booking": False,
        "last_completed_booking_client_id": None,
        "slots_locked_reason": None,
        "bookings_locked_reason": None,
    }

    pending_ttv_unlock = (
        st == TRAINER_STATUS_PENDING_PROFILE
        and tt_minimal_complete
        and await trainer_has_crm_access(session, trainer_id)
    )

    if not is_active and not pending_ttv_unlock:
        reason = _SLOTS_BOOKINGS_LOCKED_PENDING_RU if st == TRAINER_STATUS_PENDING_PROFILE else _SLOTS_BOOKINGS_LOCKED_RU
        out["slots_locked_reason"] = reason
        out["bookings_locked_reason"] = reason
        out["schedule_unlocked"] = False
        return out

    r_tpl = await session.execute(
        text("SELECT COUNT(*)::int FROM trainer_schedule_templates WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    tpl_row = r_tpl.fetchone()
    out["weekly_template_count"] = int(tpl_row[0]) if tpl_row and tpl_row[0] is not None else 0

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

    r_upcoming = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status IN ('pending', 'confirmed')
                  AND s.status IN ('available', 'booked')
                  AND """
            + _SQL_SLOT_END_TS
            + """
                  > CURRENT_TIMESTAMP
            )
            """
        ),
        {"tid": trainer_id},
    )
    out["has_upcoming_booking"] = bool(r_upcoming.scalar())

    r3 = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM bookings
                WHERE trainer_id = :tid
                  AND status IN ('confirmed', 'completed')
            )
            """
        ),
        {"tid": trainer_id},
    )
    out["has_confirmed_booking"] = bool(r3.scalar())

    r_done = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM bookings
                WHERE trainer_id = :tid AND status = 'completed'
            )
            """
        ),
        {"tid": trainer_id},
    )
    out["has_completed_booking"] = bool(r_done.scalar())
    r_last_done = await session.execute(
        text(
            """
            SELECT client_id FROM bookings
            WHERE trainer_id = :tid AND status = 'completed'
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"tid": trainer_id},
    )
    row_last = r_last_done.fetchone()
    out["last_completed_booking_client_id"] = (
        int(row_last[0]) if row_last and row_last[0] is not None else None
    )

    out["schedule_unlocked"] = bool(is_active or pending_ttv_unlock)
    return out
