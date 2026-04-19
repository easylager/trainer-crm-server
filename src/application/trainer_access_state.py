"""
Trainer bot access: map DB trainer.status + profile completeness to a small enum.
Aligned with admin moderation (pending_profile queue → approve → active).
"""
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_link import get_trainer_row_by_telegram_id
from src.application.trainer_profile_completeness import (
    is_profile_complete_for_moderation,
    is_tt_minimal_profile_complete,
)
from src.application.trainer_use_cases import get_trainer
from src.shared.trainer_status import normalize_trainer_status_value
from src.infrastructure.db.models import (
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_CONTRACT,
    TRAINER_STATUS_PENDING_PAYMENT,
    TRAINER_STATUS_PENDING_PROFILE,
)


class TrainerAccessState(str, Enum):
    """Who may use schedule/bookings/requests/etc. in the trainer bot."""

    NOT_LINKED = "not_linked"
    ACTIVE = "active"
    BLOCKED_PROFILE = "blocked_profile"
    # pending_profile + TTV minimal: Mini App schedule/bookings; bot stays gated until active.
    BOOKING_READY = "booking_ready"
    PENDING_MODERATION = "pending_moderation"
    DEACTIVATED = "deactivated"


def resolve_trainer_access_state(*, status: str, trainer: dict[str, Any] | None) -> TrainerAccessState:
    """Pure mapping for tests and single place for rules."""
    st = (status or "").strip().lower()
    if st == TRAINER_STATUS_ACTIVE:
        return TrainerAccessState.ACTIVE
    if st == TRAINER_STATUS_DEACTIVATED:
        return TrainerAccessState.DEACTIVATED
    if st in (TRAINER_STATUS_PENDING_CONTRACT, TRAINER_STATUS_PENDING_PAYMENT):
        return TrainerAccessState.PENDING_MODERATION
    if st == TRAINER_STATUS_PENDING_PROFILE:
        if trainer is not None and is_profile_complete_for_moderation(trainer):
            return TrainerAccessState.PENDING_MODERATION
        if trainer is not None and is_tt_minimal_profile_complete(trainer):
            return TrainerAccessState.BOOKING_READY
        return TrainerAccessState.BLOCKED_PROFILE
    return TrainerAccessState.PENDING_MODERATION


async def get_trainer_access_state(
    session: AsyncSession,
    telegram_id: int,
) -> tuple[TrainerAccessState, dict[str, Any] | None]:
    """
    Returns access state and trainer aggregate (get_trainer) when linked.
    NOT_LINKED if telegram is not bound to a trainer row.
    """
    row = await get_trainer_row_by_telegram_id(session, telegram_id)
    if not row:
        return TrainerAccessState.NOT_LINKED, None
    tid = row["id"]
    trainer = await get_trainer(session, tid)
    if not trainer:
        return TrainerAccessState.NOT_LINKED, None
    status = normalize_trainer_status_value(trainer.get("status"))
    state = resolve_trainer_access_state(status=status, trainer=trainer)
    if status == TRAINER_STATUS_ACTIVE:
        return TrainerAccessState.ACTIVE, trainer
    return state, trainer
