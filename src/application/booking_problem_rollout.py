"""
PRD E7 T7.2: gate trainer «Client problem» API by env (off / pilot allowlist / full rollout).
"""
from __future__ import annotations


def trainer_may_use_booking_problem_api(
    trainer_id: int,
    *,
    rollout: str | None = "full",
    pilot_trainer_ids: list[int] | None = None,
) -> bool:
    """
    When rollout is ``off``, no trainer may call problem-options / problem POST.
    When ``full``, all active trainers (already past auth) may use it.
    When ``pilot``, only ``trainer_id`` in ``pilot_trainer_ids`` (non-empty allowlist).
    """
    mode = (rollout or "full").strip().lower()
    if mode == "off":
        return False
    if mode == "full":
        return True
    if mode == "pilot":
        ids = pilot_trainer_ids or []
        return trainer_id in ids
    # Misconfiguration: fail closed for safety.
    return False


def booking_problem_api_allowed_for_trainer(
    trainer_id: int,
    settings: object | None = None,
) -> bool:
    """Reads rollout fields from Settings (single entry point for API layer)."""
    if settings is None:
        from src.shared.config import Settings

        settings = Settings()
    return trainer_may_use_booking_problem_api(
        trainer_id,
        rollout=settings.booking_problem_rollout,
        pilot_trainer_ids=settings.booking_problem_pilot_trainer_ids,
    )
