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


def trainer_first_link_onboarding_html(state: TrainerAccessState, trainer: dict[str, Any] | None) -> str:
    """
    Single HTML message after successful welcome link (non-active): value prop + clear next step.
    Replaces dry TRAINER_LINK_SUCCESS + gate wall of text.
    """
    if state == TrainerAccessState.DEACTIVATED:
        return msg.TRAINER_AFTER_LINK_STEP_DEACTIVATED
    hero = msg.TRAINER_AFTER_LINK_HERO
    step = _after_link_step_html(state, trainer)
    return f"{hero}\n\n{step}"


def _after_link_step_html(state: TrainerAccessState, trainer: dict[str, Any] | None) -> str:
    if state == TrainerAccessState.NOT_LINKED:
        return msg.TRAINER_ONLY_VIA_SITE
    if state == TrainerAccessState.BLOCKED_PROFILE:
        return msg.TRAINER_AFTER_LINK_STEP_BLOCKED
    if state == TrainerAccessState.BOOKING_READY:
        return msg.TRAINER_AFTER_LINK_STEP_BOOKING_READY
    if state == TrainerAccessState.PENDING_MODERATION:
        t = trainer or {}
        st = (t.get("status") or "").strip()
        if st in (TRAINER_STATUS_PENDING_CONTRACT, TRAINER_STATUS_PENDING_PAYMENT):
            return msg.TRAINER_AFTER_LINK_STEP_AWAITING_ACTIVATION
        fb = t.get("moderation_feedback")
        if fb and str(fb).strip():
            return msg.TRAINER_AFTER_LINK_STEP_NEEDS_EDIT.format(
                feedback=html.escape(str(fb).strip()),
            )
        if st == TRAINER_STATUS_PENDING_PROFILE:
            ready = moderation_readiness_dict(t, trainer_status=st)
            if ready.get("complete") and not ready.get("already_submitted_for_moderation"):
                return msg.TRAINER_AFTER_LINK_STEP_INVITE_SUBMIT
        return msg.TRAINER_AFTER_LINK_STEP_PENDING
    return msg.TRAINER_AFTER_LINK_STEP_PENDING  # fallback


def trainer_gate_message(state: TrainerAccessState, trainer: dict[str, Any] | None) -> str:
    if state == TrainerAccessState.NOT_LINKED:
        return msg.TRAINER_ONLY_VIA_SITE
    if state == TrainerAccessState.BLOCKED_PROFILE:
        return msg.TRAINER_GATE_BLOCKED_PROFILE
    if state == TrainerAccessState.BOOKING_READY:
        return msg.TRAINER_GATE_BOOKING_READY
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
