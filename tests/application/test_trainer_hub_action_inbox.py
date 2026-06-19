"""Unit tests for trainer hub unified action inbox builder (Wave B)."""
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.application.trainer_hub_action_inbox import (
    HUB_RHYTHM_GROWTH_MAX,
    _cap_hub_inbox_rhythm_items,
    _rhythm_show_slots_next_week_hint,
    _rhythm_show_slots_this_week_hint,
    build_hub_dual_summary,
    build_trainer_hub_action_inbox,
    build_trainer_hub_inbox_badges,
)


def test_cap_hub_inbox_rhythm_items_urgent_never_capped() -> None:
    items = [
        {"kind": "pending", "priority": 100, "id": "pending_bookings"},
        {"kind": "rhythm", "priority": 100, "id": "slots_this_week", "urgent": True},
        {"kind": "rhythm", "priority": 97, "id": "open_loop_no_next", "urgent": True},
        {"kind": "rhythm", "priority": 104, "id": "template", "urgent": False},
    ]
    capped = _cap_hub_inbox_rhythm_items(items)
    rhythm = [x for x in capped if x["kind"] == "rhythm"]
    assert len(rhythm) == 3
    assert any(x["id"] == "pending_bookings" for x in capped)


def test_cap_hub_inbox_rhythm_items_growth_only() -> None:
    items = [
        {"kind": "rhythm", "priority": 72, "id": "share_link"},
        {"kind": "rhythm", "priority": 66, "id": "referral_growth"},
        {"kind": "rhythm", "priority": 40, "id": "client_notes"},
    ]
    capped = _cap_hub_inbox_rhythm_items(items)
    rhythm = [x for x in capped if x["kind"] == "rhythm"]
    assert len(rhythm) == HUB_RHYTHM_GROWTH_MAX
    assert [x["id"] for x in rhythm] == ["share_link", "referral_growth"]


def _onboarding_slots_rhythm_fixture() -> dict:
    return {
        "is_active": True,
        "profile_complete": True,
        "has_any_booking": True,
        "has_completed_booking": True,
        "has_crm_subscription_access": True,
        "weekly_template_count": 1,
        "available_slots_this_week_count": 0,
        "available_slots_next_week_count": 0,
        "slots_this_week_count": 0,
        "slots_next_week_count": 0,
        "bookings_this_week_count": 0,
        "bookings_next_week_count": 0,
        "open_loop_clients_no_upcoming_count": 0,
        "open_loop_clients_no_telegram_count": 0,
        "fill_slots_invite_candidates_count": 0,
        "has_future_available_slots": False,
    }


@patch("src.application.trainer_hub_action_inbox.datetime")
def test_slots_this_week_hint_monday_only(mock_dt) -> None:
    mock_dt.now.return_value = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("Europe/Minsk"))
    assert _rhythm_show_slots_this_week_hint() is True
    assert _rhythm_show_slots_next_week_hint() is False
    inbox = build_trainer_hub_action_inbox(
        onboarding=_onboarding_slots_rhythm_fixture(),
        requests_count=0,
        bookings=None,
        schedule_unlocked=True,
    )
    ids = {it["id"] for it in inbox["items"]}
    assert "slots_this_week" in ids
    assert "slots_next_week" not in ids


@patch("src.application.trainer_hub_action_inbox.datetime")
def test_slots_next_week_hint_thursday_only(mock_dt) -> None:
    mock_dt.now.return_value = datetime(2026, 6, 18, 12, 0, tzinfo=ZoneInfo("Europe/Minsk"))
    assert _rhythm_show_slots_this_week_hint() is False
    assert _rhythm_show_slots_next_week_hint() is True
    inbox = build_trainer_hub_action_inbox(
        onboarding=_onboarding_slots_rhythm_fixture(),
        requests_count=0,
        bookings=None,
        schedule_unlocked=True,
    )
    ids = {it["id"] for it in inbox["items"]}
    assert "slots_next_week" in ids
    assert "slots_this_week" not in ids


def test_action_inbox_pending_and_requests() -> None:
    onboarding = {
        "is_active": True,
        "profile_complete": True,
        "has_any_booking": True,
        "schedule_unlocked": True,
        "open_loop_pending_bookings_count": 2,
        "has_crm_subscription_access": True,
        "weekly_template_count": 1,
        "available_slots_this_week_count": 1,
        "available_slots_next_week_count": 1,
        "slots_this_week_count": 1,
        "slots_next_week_count": 1,
        "bookings_this_week_count": 2,
        "bookings_next_week_count": 2,
        "open_loop_clients_no_upcoming_count": 0,
        "open_loop_clients_no_telegram_count": 0,
        "fill_slots_invite_candidates_count": 0,
        "has_future_available_slots": True,
    }
    bookings = {
        "days": [
            {
                "date": "2026-06-15",
                "day_label": "Пн",
                "bookings": [
                    {"id": 101, "status": "pending"},
                    {"id": 102, "status": "pending"},
                ],
            }
        ]
    }
    inbox = build_trainer_hub_action_inbox(
        onboarding=onboarding,
        requests_count=1,
        bookings=bookings,
        schedule_unlocked=True,
    )
    assert inbox["total_actionable"] >= 2
    kinds = {it["id"] for it in inbox["items"]}
    assert "pending_bookings" in kinds
    assert "unanswered_requests" in kinds
    pending = next(it for it in inbox["items"] if it["id"] == "pending_bookings")
    assert pending["booking_ids"] == [101, 102]
    assert pending["primary_action"] == "batch_confirm"
    assert "open_loop_pending" not in kinds


def test_inbox_badges_schedule_and_clients() -> None:
    onboarding = {
        "is_active": True,
        "profile_complete": False,
        "has_any_booking": True,
        "is_catalog_visible": False,
        "open_loop_clients_no_telegram_count": 3,
    }
    badges = build_trainer_hub_inbox_badges(
        onboarding=onboarding,
        requests_count=2,
        pending_count=4,
    )
    assert badges["schedule"] == 4
    assert badges["more"] == 2  # requests only — catalog profile hint is optional, not tab-dot urgent
    assert badges["clients"] == 3
    assert badges["menu"]["trainer-requests"] == 2
    assert badges["menu"]["trainer-profile"] == 1
    assert "новые заявки" in badges["menu_hints"]["trainer-requests"]
    assert badges["menu_hints"]["trainer-profile"] == "Можно дополнить анкету — каталог по желанию"


def test_action_inbox_hidden_when_schedule_locked() -> None:
    onboarding = {
        "open_loop_pending_bookings_count": 5,
        "is_active": False,
        "schedule_unlocked": False,
    }
    inbox = build_trainer_hub_action_inbox(
        onboarding=onboarding,
        requests_count=0,
        bookings=None,
        schedule_unlocked=False,
    )
    assert not any(it["id"] == "pending_bookings" for it in inbox["items"])


def test_action_inbox_uses_explicit_pending_booking_ids() -> None:
    """Pending count from onboarding; IDs may come from DB outside bookings preview."""
    onboarding = {"open_loop_pending_bookings_count": 1}
    inbox = build_trainer_hub_action_inbox(
        onboarding=onboarding,
        requests_count=0,
        bookings={"days": []},
        schedule_unlocked=True,
        pending_booking_ids=[555],
    )
    pending = next(it for it in inbox["items"] if it["id"] == "pending_bookings")
    assert pending["count"] == 1
    assert pending["booking_ids"] == [555]


def test_action_inbox_center_pending_for_hybrid_admin() -> None:
    inbox = build_trainer_hub_action_inbox(
        onboarding={"open_loop_pending_bookings_count": 0},
        requests_count=0,
        bookings=None,
        schedule_unlocked=True,
        center_inbox_pending=3,
        show_center_inbox=True,
    )
    center = next(it for it in inbox["items"] if it["id"] == "center_session_bookings")
    assert center["kind"] == "center_pending"
    assert center["count"] == 3
    assert center["primary_action"] == "schedule_editor"
    assert inbox["badges"]["center"] == 3


def test_build_hub_dual_summary() -> None:
    summary = build_hub_dual_summary(
        bookings={"today_sessions": {"total": 4, "remaining": 2}},
        center_inbox_pending=1,
        collective_slug="broski",
        collective_label="Центр",
    )
    assert summary["personal_today_total"] == 4
    assert summary["personal_today_remaining"] == 2
    assert summary["center_inbox_pending"] == 1
    assert summary["collective_slug"] == "broski"
