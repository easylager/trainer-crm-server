"""Admin moderation queue eligibility — same rules as /pending in admin bot."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_profile_completeness import is_ready_for_moderation_submission
from src.application.trainer_profile_pending import (
    trainer_has_pending_text_revision,
    trainer_has_photo_pending_revision,
)
from src.application.trainer_use_cases import get_trainer
from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE, TRAINER_STATUS_PENDING_PROFILE
from src.infrastructure.repositories import TrainerRepository


async def list_trainer_ids_eligible_for_admin_moderation(session: AsyncSession) -> list[int]:
    """Trainer IDs the admin /pending command would show (ready profile or active edits)."""
    repo = TrainerRepository(session)
    queue_ids = await repo.list_trainer_ids_for_moderation_queue()
    eligible_ids: list[int] = []
    for tid in queue_ids:
        full = await get_trainer(session, tid)
        if not full:
            continue
        st = (full.get("status") or "").strip()
        if st == TRAINER_STATUS_ACTIVE:
            sub_at = full.get("moderation_submitted_at")
            has_queue = bool(sub_at) and (
                trainer_has_pending_text_revision(full) or trainer_has_photo_pending_revision(full)
            )
            if has_queue:
                eligible_ids.append(int(tid))
        elif st == TRAINER_STATUS_PENDING_PROFILE and is_ready_for_moderation_submission(full):
            eligible_ids.append(int(tid))
    return eligible_ids


async def count_trainers_eligible_for_admin_moderation(session: AsyncSession) -> int:
    """Count of trainers waiting in the admin moderation queue."""
    return len(await list_trainer_ids_eligible_for_admin_moderation(session))
