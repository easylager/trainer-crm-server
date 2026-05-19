from __future__ import annotations

from datetime import datetime, timezone

from src.application.trial_roi_recap_use_cases import TrialRoiRecap
from src.bot.messages import format_trainer_trial_roi_recap_html
from src.shared.byr_currency_display import BYR_SIGN


def _recap(**overrides) -> TrialRoiRecap:
    base = {
        "trainer_id": 1,
        "period_start": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "period_end": datetime(2026, 4, 11, tzinfo=timezone.utc),
        "completed_sessions_count": 11,
        "self_bookings_count": 4,
        "self_confirmations_count": 3,
        "repeat_bookings_count": 3,
        "future_available_slots_count": 4,
        "auto_reminders_sent_count": 8,
        "pass_redemptions_count": 2,
        "certificate_credits_count": 1,
        "revenue_sessions_cents": 12000,
        "revenue_pass_sales_cents": 20000,
        "revenue_certificate_sales_cents": 10000,
    }
    base.update(overrides)
    return TrialRoiRecap(**base)


def test_trial_roi_saved_minutes_rounds_to_believable_bucket() -> None:
    recap = _recap()

    assert recap.saved_minutes_raw == 44.5
    assert recap.saved_minutes_display == 45


def test_trial_roi_message_anchors_value_without_sales_cta() -> None:
    text = format_trainer_trial_roi_recap_html(
        recap=_recap(),
        expires_date="15.04.2026",
        days_until_expiry=2,
    )

    assert "<b>Короткая сводка по пробному периоду</b>" in text
    assert "провести <b>11</b> тренировок" in text
    assert "≈ <b>45 минут рутины снято</b>" in text
    assert f"Разовые занятия: <b>120 {BYR_SIGN}</b>" in text
    assert f"Абонементы: <b>200 {BYR_SIGN}</b>" in text
    assert f"Сертификаты: <b>100 {BYR_SIGN}</b>" in text
    assert f"Итого в учёте: <b>420 {BYR_SIGN}</b>" in text
    assert "Через <b>2 дня</b> <b>пробный период</b> закончится" in text
    assert "профиль останется в каталоге" in text
    assert "<b>Пробный период</b> действует до 15.04.2026" in text
    # D-2 is mental anchoring, not the decision ask. CTA-style copy lives in D-1, not here.
    for sales_phrase in ("Продлить", "Вернуть контроль", "👇"):
        assert sales_phrase not in text


def test_trial_roi_message_pluralizes_days_until_expiry() -> None:
    one_day = format_trainer_trial_roi_recap_html(
        recap=_recap(),
        expires_date="15.04.2026",
        days_until_expiry=1,
    )
    five_days = format_trainer_trial_roi_recap_html(
        recap=_recap(),
        expires_date="15.04.2026",
        days_until_expiry=5,
    )

    assert "Через <b>1 день</b> <b>пробный период</b> закончится" in one_day
    assert "Через <b>5 дней</b> <b>пробный период</b> закончится" in five_days


def test_trial_roi_message_omits_revenue_block_when_zero() -> None:
    text = format_trainer_trial_roi_recap_html(
        recap=_recap(
            revenue_sessions_cents=0,
            revenue_pass_sales_cents=0,
            revenue_certificate_sales_cents=0,
        ),
        expires_date="15.04.2026",
        days_until_expiry=2,
    )

    assert "Деньги, которые уже прошли через систему" not in text
    assert "Итого в учёте" not in text
