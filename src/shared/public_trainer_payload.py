"""
Strip internal fields from trainer aggregates returned by /api/public/* (catalog).
Admin and authenticated webapp routes keep full payloads from get_trainer / repository.
"""

from __future__ import annotations

# Moderation and linkage ids are not needed for catalog UX and reduce unnecessary exposure.
_PUBLIC_TRAINER_DROP_KEYS = frozenset(
    {
        "telegram_id",
        "moderation_feedback",
        "moderation_submitted_at",
        "created_at",
    }
)


def sanitize_trainer_for_public_catalog(trainer: dict) -> dict:
    """Return a shallow copy without internal-only top-level keys."""
    return {k: v for k, v in trainer.items() if k not in _PUBLIC_TRAINER_DROP_KEYS}
