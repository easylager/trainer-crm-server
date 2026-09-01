"""
Trainer bot access: map DB trainer row to a small enum.

Onboarding v2 invariant: **moderation gates the public catalog, not the trainer's own tools.**
A linked trainer works from the first second — schedule, slots, bookings, clients, notes.
``trainers.status`` stays the *catalog* moderation state (public listings already filter
``status = 'active'``); it no longer decides whether the trainer may use the product.

Three states, no completeness tiers:

* ``NOT_LINKED``  — this Telegram account is not bound to a trainer row.
* ``ACTIVE``      — linked and working. Everything operational is open.
* ``DEACTIVATED`` — linked but switched off by an admin.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application.trainer_link import get_trainer_row_by_telegram_id, get_trainer_row_for_miniapp_principal
from src.application.trainer_use_cases import get_trainer
from src.infrastructure.db.models import TRAINER_STATUS_DEACTIVATED
from src.shared.trainer_status import normalize_trainer_status_value


class TrainerAccessState(str, Enum):
    """Who may use schedule/bookings/requests/etc. in the trainer bot."""

    NOT_LINKED = "not_linked"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


def trainer_may_use_bot_workflows(state: TrainerAccessState) -> bool:
    """Trainer-bot handlers (callbacks, CRM messages) run for linked, non-deactivated trainers."""
    return state == TrainerAccessState.ACTIVE


def resolve_trainer_access_state(*, status: str, trainer: dict[str, Any] | None) -> TrainerAccessState:
    """
    Pure mapping for tests and single place for rules.

    ``trainer`` is accepted for call-site compatibility and is deliberately unused: access no
    longer depends on profile completeness. Only an explicit ``deactivated`` status closes the door.
    """
    st = normalize_trainer_status_value(status)
    if st == TRAINER_STATUS_DEACTIVATED:
        return TrainerAccessState.DEACTIVATED
    return TrainerAccessState.ACTIVE


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
    trainer = await get_trainer(session, row["id"])
    if not trainer:
        return TrainerAccessState.NOT_LINKED, None
    state = resolve_trainer_access_state(status=trainer.get("status"), trainer=trainer)
    return state, trainer


async def get_trainer_access_state_from_principal(
    session: AsyncSession,
    principal: MiniAppPrincipal,
) -> tuple[TrainerAccessState, dict[str, Any] | None]:
    """Same as :func:`get_trainer_access_state` but resolves link via Telegram or VK id from Mini App."""
    row = await get_trainer_row_for_miniapp_principal(session, principal)
    if not row:
        return TrainerAccessState.NOT_LINKED, None
    trainer = await get_trainer(session, row["id"])
    if not trainer:
        return TrainerAccessState.NOT_LINKED, None
    state = resolve_trainer_access_state(status=trainer.get("status"), trainer=trainer)
    return state, trainer
