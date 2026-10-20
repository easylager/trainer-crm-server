"""Когда хаб зовёт «Добавьте учеников» (TASK-310) — гейт по ученикам, а не по записям."""
from __future__ import annotations

from src.application.trainer_hub_action_inbox import _build_hub_rhythm_inbox_candidates


def _ids(**over) -> set[str]:
    d = {
        "schedule_unlocked": True,
        "weekly_template_count": 0,
        "has_future_slots": True,
        "crm_clients_count": 0,
        "real_bookings_count": 0,
        "has_real_booking": False,
        "has_completed_booking": False,
        "has_crm_subscription_access": True,
    }
    d.update(over)
    return {x["id"] for x in _build_hub_rhythm_inbox_candidates(d)}


def test_week_without_students_asks_for_them_instead_of_the_link() -> None:
    ids = _ids()
    assert "first_students" in ids
    assert "share_link" not in ids


def test_one_weekly_student_keeps_the_step() -> None:
    """«Каждую неделю» для первого ученика даёт три записи — шаг не должен пропасть."""
    assert "first_students" in _ids(crm_clients_count=1, real_bookings_count=3, has_real_booking=True)


def test_three_students_close_the_step() -> None:
    assert "first_students" not in _ids(crm_clients_count=3, has_real_booking=True)


def test_working_trainer_with_a_held_session_is_not_onboarded_again() -> None:
    assert "first_students" not in _ids(crm_clients_count=2, has_real_booking=True, has_completed_booking=True)


def test_no_schedule_no_step() -> None:
    assert "first_students" not in _ids(has_future_slots=False, onboarding_completed=True)
