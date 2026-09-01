"""
User-visible texts for trainer bot access gate (shared by middleware and /start).

Onboarding v2: there are only two things to say. Either this Telegram account is not a trainer
here yet, or the account was switched off. A linked, working trainer never sees a gate — the
catalog moderation state is shown inside the app, not as a wall in chat.
"""
from typing import Any

from src.application.trainer_access_state import TrainerAccessState
from src.bot import messages as msg


def trainer_first_link_onboarding_html(state: TrainerAccessState, trainer: dict[str, Any] | None) -> str:
    """Single HTML message right after a successful welcome link: one promise, one action."""
    if state == TrainerAccessState.DEACTIVATED:
        return msg.TRAINER_AFTER_LINK_STEP_DEACTIVATED
    if state == TrainerAccessState.NOT_LINKED:
        return msg.TRAINER_ONLY_VIA_SITE
    return msg.TRAINER_AFTER_LINK_HERO


def trainer_gate_message(state: TrainerAccessState, trainer: dict[str, Any] | None) -> str:
    if state == TrainerAccessState.NOT_LINKED:
        return msg.TRAINER_ONLY_VIA_SITE
    if state == TrainerAccessState.DEACTIVATED:
        return msg.TRAINER_GATE_DEACTIVATED
    # ACTIVE never hits a gate; keep a safe, non-alarming fallback.
    return msg.TRAINER_GATE_DEACTIVATED
