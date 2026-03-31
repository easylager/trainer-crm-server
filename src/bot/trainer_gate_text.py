"""User-visible texts for trainer bot access gate (shared by middleware and /start)."""
import html
from typing import Any

from src.application.trainer_access_state import TrainerAccessState
from src.application.trainer_profile_completeness import moderation_readiness_dict
from src.bot import messages as msg
from src.infrastructure.db.models import (
    TRAINER_STATUS_PENDING_CONTRACT,
    TRAINER_STATUS_PENDING_PAYMENT,
    TRAINER_STATUS_PENDING_PROFILE,
)


def trainer_gate_message(state: TrainerAccessState, trainer: dict[str, Any] | None) -> str:
    if state == TrainerAccessState.NOT_LINKED:
        return msg.TRAINER_ONLY_VIA_SITE
    if state == TrainerAccessState.BLOCKED_PROFILE:
        return msg.TRAINER_GATE_BLOCKED_PROFILE
    if state == TrainerAccessState.PENDING_MODERATION:
        t = trainer or {}
        st = (t.get("status") or "").strip()
        # Договор/оплата важнее редкого хвоста moderation_feedback на этом статусе.
        if st in (TRAINER_STATUS_PENDING_CONTRACT, TRAINER_STATUS_PENDING_PAYMENT):
            return msg.TRAINER_GATE_AWAITING_ACTIVATION
        fb = t.get("moderation_feedback")
        if fb and str(fb).strip():
            return msg.TRAINER_GATE_NEEDS_EDIT.format(
                feedback=html.escape(str(fb).strip()),
            )
        if st == TRAINER_STATUS_PENDING_PROFILE:
            ready = moderation_readiness_dict(t, trainer_status=st)
            if ready.get("complete") and not ready.get("already_submitted_for_moderation"):
                return msg.TRAINER_GATE_INVITE_SUBMIT
        return msg.TRAINER_GATE_PENDING_MODERATION
    if state == TrainerAccessState.DEACTIVATED:
        return msg.TRAINER_GATE_DEACTIVATED
    return msg.TRAINER_GATE_PENDING_MODERATION
