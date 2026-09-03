"""Unit tests for trainer hub unified action inbox builder (Wave B)."""
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.application.trainer_next_step import CATALOG_INVITE_MIN_BOOKINGS
from src.application.trainer_hub_action_inbox import (
    HUB_RHYTHM_GROWTH_MAX,
    _cap_hub_inbox_rhythm_items,
    _rhythm_show_slots_next_week_hint,
    _rhythm_show_slots_this_week_hint,
    _should_nudge_catalog_in_hub,
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


def test_early_practice_gets_no_catalog_hub_nudge() -> None:
    onboarding = {
        "is_active": False,
        "profile_complete": False,
        "has_any_booking": True,
        "real_bookings_count": 1,
        "is_catalog_visible": True,
        "weekly_template_count": 1,
        "has_future_slots": True,
    }
    assert not _should_nudge_catalog_in_hub(onboarding)
    inbox = build_trainer_hub_action_inbox(
        onboarding=onboarding,
        requests_count=0,
        bookings=None,
        schedule_unlocked=True,
    )
    assert "catalog_publication" not in {it["id"] for it in inbox["items"]}
    badges = build_trainer_hub_inbox_badges(
        onboarding=onboarding,
        requests_count=0,
        pending_count=0,
    )
    assert badges["menu"]["trainer-profile"] == 0


def test_inbox_badges_schedule_and_clients() -> None:
    onboarding = {
        "is_active": True,
        "profile_complete": False,
        "has_any_booking": True,
        "has_real_booking": True,
        # Каталог теперь по заявке: подсказка про профиль появляется только при живом потоке
        # записей. Раньше её триггерил сам факт «активен, но не в каталоге» — то есть тренер,
        # который сам выключил показ, получал бейдж «доделай профиль».
        "real_bookings_count": CATALOG_INVITE_MIN_BOOKINGS,
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


def test_rhythm_hints_visible_for_unmoderated_trainer_with_a_real_schedule() -> None:
    """
    Регрессия онбординга v2: рабочий тренер без модерации (is_active=False) должен видеть
    ритм-подсказки (пустые слоты, шаблон, рефералы) наравне с тем, кто уже в каталоге.
    Раньше блок гейтился по is_active + старому «tt_minimal_complete», и молчал для
    любого немодерированного тренера — даже с рабочим расписанием и записями.
    """
    onboarding = {
        "is_active": False,
        "is_catalog_visible": True,
        "profile_complete": False,
        "has_any_booking": True,
        "has_confirmed_booking": True,
        "has_real_booking": True,
        "weekly_template_count": 3,
        "has_future_slots": True,
        "has_future_available_slots": False,
        "slots_this_week_count": 0,
        "available_slots_this_week_count": 0,
        "bookings_this_week_count": 0,
        "has_crm_subscription_access": True,
    }
    with patch(
        "src.application.trainer_hub_action_inbox._minsk_weekday_mon0",
        return_value=0,
    ):
        payload = build_trainer_hub_action_inbox(onboarding=onboarding, schedule_unlocked=True)

    ids = [x["id"] for x in payload["items"]]
    assert "slots_this_week" in ids, "пустая неделя должна быть видна без модерации"
    assert "referral_growth" in ids, "рефералка не должна требовать статуса в каталоге"


def test_rhythm_hints_stay_silent_before_the_first_schedule() -> None:
    """До первого расписания (первый экран онбординга) ритм-блоку нечего показывать."""
    onboarding = {
        "is_active": False,
        "is_catalog_visible": True,
        "profile_complete": False,
        "has_any_booking": False,
        "weekly_template_count": 0,
        "has_future_slots": False,
        "has_crm_subscription_access": True,
    }
    payload = build_trainer_hub_action_inbox(onboarding=onboarding, schedule_unlocked=True)
    assert payload["items"] == []


def test_referral_growth_waits_for_a_first_booking() -> None:
    """
    Регрессия: реферальная программа («пригласите коллегу») не должна конкурировать с
    карточкой «следующий шаг» («пригласите своего ученика») в первые же секунды после
    quick-setup — до того, как у тренера появилась хоть одна запись.
    """
    fresh_schedule = {
        "is_active": False,
        "is_catalog_visible": True,
        "profile_complete": False,
        "has_any_booking": False,
        "weekly_template_count": 3,
        "has_future_slots": True,
        "has_crm_subscription_access": True,
        "available_slots_this_week_count": 5,
        "bookings_this_week_count": 0,
    }
    payload = build_trainer_hub_action_inbox(onboarding=fresh_schedule, schedule_unlocked=True)
    ids = [x["id"] for x in payload["items"]]
    assert "referral_growth" not in ids

    after_first_booking = dict(fresh_schedule, has_any_booking=True, has_real_booking=True)
    payload2 = build_trainer_hub_action_inbox(onboarding=after_first_booking, schedule_unlocked=True)
    ids2 = [x["id"] for x in payload2["items"]]
    assert "referral_growth" in ids2


def test_catalog_hub_nudge_respects_not_now() -> None:
    """«Не сейчас» — ответ, а не состояние вкладки: он хранится на сервере и гасит подсказку."""
    onboarding = {
        "is_active": False,
        "profile_complete": False,
        "has_any_booking": True,
        "has_real_booking": True,
        "real_bookings_count": CATALOG_INVITE_MIN_BOOKINGS + 3,
        "is_catalog_visible": False,
        "weekly_template_count": 1,
        "has_future_slots": True,
    }
    assert _should_nudge_catalog_in_hub(onboarding)
    assert not _should_nudge_catalog_in_hub({**onboarding, "catalog_invite_dismissed": True})


def test_active_trainer_who_hid_catalog_is_not_nudged() -> None:
    """
    Выключенный показ в каталоге — решение тренера, а не незакрытая задача.

    Раньше эта комбинация (active + is_catalog_visible=false) сама по себе поднимала подсказку
    «включите показ», сколько бы раз тренер её ни закрывал.
    """
    onboarding = {
        "is_active": True,
        "profile_complete": True,
        "has_any_booking": True,
        "real_bookings_count": 1,
        "is_catalog_visible": False,
        "weekly_template_count": 1,
        "has_future_slots": True,
    }
    assert not _should_nudge_catalog_in_hub(onboarding)


# ──────────────────────────────────────────────────────────────────────────
# TASK-029: server-side snooze filtering + EDGE-002 (urgent hints never dismissible)
# ──────────────────────────────────────────────────────────────────────────


def test_active_snoozes_hide_a_rhythm_candidate() -> None:
    onboarding = {
        "is_active": False,
        "is_catalog_visible": True,
        "profile_complete": False,
        "has_any_booking": True,
        "has_real_booking": True,
        "weekly_template_count": 3,
        "has_future_slots": True,
        "has_crm_subscription_access": True,
    }
    without_snooze = build_trainer_hub_action_inbox(onboarding=onboarding, schedule_unlocked=True)
    ids_before = [x["id"] for x in without_snooze["items"]]
    assert "referral_growth" in ids_before

    with_snooze = build_trainer_hub_action_inbox(
        onboarding=onboarding,
        schedule_unlocked=True,
        active_hint_snoozes={"referral_growth": "2099-01-01"},
    )
    ids_after = [x["id"] for x in with_snooze["items"]]
    assert "referral_growth" not in ids_after


def test_open_loop_no_next_and_slots_this_week_are_not_dismissible() -> None:
    """TASK-029 EDGE-002/DEC-004: urgent hints must never carry dismissible=True."""
    onboarding = {
        "is_active": False,
        "is_catalog_visible": True,
        "profile_complete": False,
        "has_any_booking": True,
        "weekly_template_count": 3,
        "has_future_slots": True,
        "has_crm_subscription_access": True,
        "has_future_available_slots": False,
        "open_loop_clients_no_upcoming_count": 2,
        "available_slots_this_week_count": 0,
        "bookings_this_week_count": 0,
    }
    with patch(
        "src.application.trainer_hub_action_inbox._minsk_weekday_mon0",
        return_value=0,
    ):
        payload = build_trainer_hub_action_inbox(onboarding=onboarding, schedule_unlocked=True)
    by_id = {x["id"]: x for x in payload["items"]}
    assert "open_loop_no_next" in by_id
    assert by_id["open_loop_no_next"]["dismissible"] is False
    assert "slots_this_week" in by_id
    assert by_id["slots_this_week"]["dismissible"] is False


def test_snooze_cannot_hide_an_always_urgent_hint_even_if_passed() -> None:
    """DEC-002: urgent hints are never dismissible "ни на клиенте, ни на сервере" — the
    filter itself excludes NON_DISMISSIBLE_URGENT_HINT_IDS, not just the dismiss endpoint's
    write-side allowlist, so a stray/future snooze row for one of these ids (should never
    exist, but defense-in-depth) still can't hide it from the response."""
    onboarding = {
        "is_active": False,
        "is_catalog_visible": True,
        "profile_complete": False,
        "has_any_booking": True,
        "weekly_template_count": 3,
        "has_future_slots": True,
        "has_crm_subscription_access": True,
        "has_future_available_slots": False,
        "open_loop_clients_no_upcoming_count": 2,
    }
    payload = build_trainer_hub_action_inbox(
        onboarding=onboarding,
        schedule_unlocked=True,
        active_hint_snoozes={"open_loop_no_next": "2099-01-01"},
    )
    ids = [x["id"] for x in payload["items"]]
    assert "open_loop_no_next" in ids
