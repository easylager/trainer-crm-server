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
    assert "Остаток по абонементу" not in text


def test_trainer_wrapup_pass_expected_with_remaining_after_current() -> None:
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
        pass_sessions_remaining=4,
    )
    assert "Оплата: абонемент" in text
    assert "Остаток по абонементу: <b>4 занятия</b>" in text


def test_trainer_wrapup_pass_remaining_plural_forms() -> None:
    for n, word in ((1, "занятие"), (2, "занятия"), (5, "занятий"), (21, "занятие"), (11, "занятий")):
        text = msg.format_session_payment_notice_html(
            phase="upcoming",
            outcome="pass",
            pass_sessions_remaining=n,
        )
        assert f"Остаток по абонементу: <b>{n} {word}</b>" in text


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


def test_client_reminder_pass_instead_of_price() -> None:
    text = msg.format_client_booking_reminder_text(
        is_soon=True,
        sessions=[
            {
                "date": "10.06",
                "day": "Ср",
                "time": "18:00",
                "duration": 60,
                "service_name": "Персональная",
                "booking_price_cents": 5000,
                "expected_payment_class": "PASS",
                "arena_name": "Зал",
                "arena_address": "ул. Тест, 1",
            }
        ],
    )
    assert "Абонемент покрывает занятие" in text
    assert "50" not in text


def test_client_trainer_booked_without_tariff_still_renders() -> None:
    """Quick-setup: услуга есть, цены нет — пуш ученику без ценника, без падения."""
    text = msg.format_client_trainer_booked_you_html(
        date="10.06",
        day="Ср",
        time="18:00",
        trainer_name="Мария",
        service_name="Персональная",
        booking_price_cents=None,
        price_tier_label=None,
        arena_name="Манеж",
        arena_address=None,
        duration_minutes=60,
        map_link=None,
        expected_payment_class=None,
    )
    assert "Персональная" in text
    assert "Вас записали" in text
    assert "💳" not in text


def test_upcoming_payment_line_empty_without_price() -> None:
    assert (
        msg.format_client_upcoming_payment_display_html(
            expected_payment_class=None,
            booking_price_cents=None,
        )
        == ""
    )
    assert (
        msg.format_session_payment_notice_html(
            phase="upcoming",
            outcome="one_off",
            booking_price_cents=None,
            for_client=True,
        )
        == ""
    )


def test_client_trainer_booked_pass_instead_of_price() -> None:
    text = msg.format_client_trainer_booked_you_html(
        date="10.06",
        day="Ср",
        time="18:00",
        trainer_name="Мария",
        service_name="Персональная",
        booking_price_cents=5000,
        price_tier_label=None,
        arena_name="Зал",
        arena_address="ул. Тест, 1",
        duration_minutes=60,
        map_link=None,
        expected_payment_class="PASS",
    )
    assert "Абонемент покрывает занятие" in text
    assert "50,00" not in text
    assert "Цена" not in text


def test_client_confirmed_pass_instead_of_price() -> None:
    text = msg.format_client_booking_confirmed_by_trainer_text(
        date="10.06",
        day="Ср",
        time="18:00",
        trainer_name="Мария",
        service_name="Персональная",
        booking_price_cents=5000,
        price_tier_label=None,
        arena_name="Зал",
        arena_address="ул. Тест, 1",
        expected_payment_class="PASS",
    )
    assert "Абонемент покрывает занятие" in text
    assert "50,00" not in text


def test_trainer_first_booking_milestone_pass_instead_of_price() -> None:
    text = msg.format_trainer_first_booking_milestone_rich_html(
        client_name="Иван",
        client_phone="+375291234567",
        date_str="10.06",
        day_label="Ср",
        time_str="18:00",
        arena_name="Зал",
        arena_address="ул. Тест, 1",
        service_name="Персональная",
        price_tier_label=None,
        booking_price_cents=5000,
        expected_payment_class="PASS",
    )
    assert "Оплата: абонемент" in text
    assert "💰" in text and "50" in text.split("💰")[1]


def test_trainer_first_booking_milestone_missing_profile_venue_and_price() -> None:
    text = msg.format_trainer_first_booking_milestone_rich_html(
        client_name="Иван",
        client_phone="+375291234567",
        date_str="01.09",
        day_label="Вт",
        time_str="06:00",
        arena_name=None,
        arena_address=None,
        service_name="Обучение катанию «с нуля»",
        price_tier_label=None,
        booking_price_cents=None,
        duration_minutes=45,
        client_has_telegram=False,
        created_by_trainer=True,
        expected_payment_class="none",
    )
    assert "перенос вашей базы" not in text
    assert "Не заполнена в профиле" in text
    assert "не указано в профиле" in text
    assert text.startswith("✅ <b>Запись создана.</b>")


def test_trainer_confirmed_echo_pass_instead_of_price() -> None:
    text = msg.format_trainer_booking_confirmed_echo_html(
        client_name="Иван",
        client_phone=None,
        date="10.06",
        day="Ср",
        time="18:00",
        duration_minutes=60,
        service_name="Персональная",
        booking_price_cents=5000,
        price_tier_label=None,
        arena_name=None,
        arena_address=None,
        expected_payment_class="PASS",
    )
    assert "Оплата: абонемент" in text
    assert "50,00" not in text
