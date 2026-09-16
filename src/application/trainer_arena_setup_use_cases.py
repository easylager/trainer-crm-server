"""
Arena setup when the trainer has no fixed venue selected: mobile format, online format, or
(historically) a text moderator request.

TASK-046 replaced the request path with real arena creation (see
``trainer_arena_create_use_cases.create_trainer_arena``) — ``submit_trainer_arena_request``
is gone and nothing creates new ``ARENA_WORK_FORMAT_PENDING_REQUEST`` rows anymore. The
constant and the TTV-gate branch below stay only to keep already-existing trainers with
that historical state correctly satisfying the gate; their old state is not backfilled.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.repositories.trainer_repository import TrainerRepository

ARENA_WORK_FORMAT_MOBILE = "mobile"
ARENA_WORK_FORMAT_ONLINE = "online"
ARENA_WORK_FORMAT_PENDING_REQUEST = "pending_request"


def tt_minimal_arenas_satisfied(trainer: dict[str, Any]) -> bool:
    """TTV gate: real arenas, mobile/online format, or a legacy pending arena request all count."""
    aids = trainer.get("arena_ids")
    if aids:
        return True
    fmt = (trainer.get("arena_work_format") or "").strip()
    if fmt in (ARENA_WORK_FORMAT_MOBILE, ARENA_WORK_FORMAT_ONLINE):
        return True
    if fmt == ARENA_WORK_FORMAT_PENDING_REQUEST:
        return bool((trainer.get("arena_request_text") or "").strip())
    return False


async def _set_trainer_arena_work_format(
    session: AsyncSession, trainer_id: int, fmt: str
) -> dict[str, Any] | None:
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return None
    await repo.set_trainer_arena_setup(
        trainer_id,
        work_format=fmt,
        request_text=None,
        request_at=None,
    )
    await session.commit()
    return await repo.get_by_id(trainer_id)


async def set_trainer_arena_mobile(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    return await _set_trainer_arena_work_format(session, trainer_id, ARENA_WORK_FORMAT_MOBILE)


async def set_trainer_arena_online(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """
    Client-visible, unlike ``mobile``: ``arena_work_format='online'`` is read by the trainer
    catalog query (``TrainerRepository.list_active_with_details``) and surfaced as an "Онлайн"
    badge on the Ice ("Лёд") coach card in place of an arena name (``ice-tab-model.js``,
    ``trainerCardView``) — a trainer with no physical arena is otherwise findable by city +
    service in Ice's coach list but shows no location line at all.
    """
    return await _set_trainer_arena_work_format(session, trainer_id, ARENA_WORK_FORMAT_ONLINE)
