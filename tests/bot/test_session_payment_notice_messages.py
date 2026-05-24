"""Session-end payment lines in trainer/client completion and wrap-up pushes."""

from __future__ import annotations

from src.bot import messages as msg


def test_trainer_completed_pass_deduction_line() -> None:
    text = msg.format_trainer_booking_completed_html(
        client_name="Иван",
        date="01.05",
        day="Чт",
        time="10:00",
        duration_minutes=60,
        service_name="Персональная",
        price_tier_label=None,
        arena_display=None,
        deduction_outcome="pass",
        pass_sessions_remaining=4,
    )
    assert "Списано 1 занятие с абонемента" in text
    assert "Осталось: <b>4</b>" in text
    assert "без списания" not in text.lower()


def test_trainer_completed_cert_deduction_line() -> None:
    text = msg.format_trainer_booking_completed_html(
        client_name="Иван",
        date="01.05",
        day="Чт",
        time="10:00",
        duration_minutes=60,
        service_name="Персональная",
        price_tier_label=None,
        arena_display=None,
        deduction_outcome="cert",
        cert_amount_cents=5000,
        cert_remaining_cents=15000,
    )
    assert "с сертификата" in text
    assert "Остаток:" in text
    assert "без списания" not in text.lower()


def test_trainer_completed_no_pass_when_none() -> None:
    text = msg.format_trainer_booking_completed_html(
        client_name="Иван",
        date="01.05",
        day="Чт",
        time="10:00",
        duration_minutes=60,
        service_name="Персональная",
        price_tier_label=None,
        arena_display=None,
        deduction_outcome="none",
    )
    assert "без списания абонемента" in text.lower()


def test_trainer_wrapup_pass_expected() -> None:
    text = msg.format_trainer_booking_session_wrapup_html(
        client_name="Иван",
        date="01.05",
        day="Чт",
        time="10:00",
        duration_minutes=60,
        service_name="Персональная",
        price_tier_label=None,
        arena_display=None,
        expected_payment_class="PASS",
    )
    assert "Оплата: абонемент" in text
    assert "спишется 1 занятие" in text


def test_trainer_wrapup_none_expected() -> None:
    text = msg.format_trainer_booking_session_wrapup_html(
        client_name="Иван",
        date="01.05",
        day="Чт",
        time="10:00",
        duration_minutes=60,
        service_name="Персональная",
        price_tier_label=None,
        arena_display=None,
        expected_payment_class="NONE",
    )
    assert "Без списания с абонемента" in text


def test_client_completed_pass_deduction_line() -> None:
    text = msg.format_client_booking_completed_notice_html(
        date="01.05",
        day="Чт",
        time="10:00",
        duration_minutes=60,
        trainer_name="Мария",
        service_name="Йога",
        deduction_outcome="pass",
        pass_sessions_remaining=2,
    )
    assert "Списано 1 занятие с абонемента" in text
    assert "Осталось: <b>2</b>" in text


def test_client_completed_silent_when_no_deduction() -> None:
    text = msg.format_client_booking_completed_notice_html(
        date="01.05",
        day="Чт",
        time="10:00",
        duration_minutes=60,
        trainer_name="Мария",
        service_name="Йога",
        deduction_outcome="none",
    )
    assert "абонемент" not in text.lower()
    assert "сертификат" not in text.lower()
