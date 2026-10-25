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
    assert "50" not in text  # абонемент — разовую цену не повторяем


def test_trainer_first_booking_milestone_omits_empty_venue_and_price_blocks() -> None:
    """
    Onboarding v2 asks for neither arena nor price, so the celebration must not turn those
    gaps into «не заполнена в профиле» lines. Missing data = missing block, not a to-do.
    """
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
    assert "профиле" not in text
    assert "Площадка" not in text
    assert "BYN" not in text
    assert "Иван" in text
    assert "ФИО" not in text
    assert text.startswith("<b>Первая запись в кабинете</b>")


def test_trainer_first_booking_milestone_without_client_phone_has_no_blank_line() -> None:
    """A client without a phone must not leave an empty row where the phone line was."""
    text = msg.format_trainer_first_booking_milestone_rich_html(
        client_name="Иван",
        client_phone="",
        date_str="01.09",
        day_label="Вт",
        time_str="06:00",
        arena_name=None,
        arena_address=None,
        service_name=None,
        price_tier_label=None,
        booking_price_cents=None,
        created_by_trainer=False,
    )
    assert "\n\n\n" not in text
    assert "\nИван\n" in text


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


def test_client_pushes_include_booked_for_child_name() -> None:
    booked = msg.format_client_trainer_booked_you_html(
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
        booked_for_name="Лера",
    )
    assert "Запись для" in booked
    assert "Лера" in booked

    reminder = msg.format_client_booking_reminder_text(
        is_soon=False,
        sessions=[
            {
                "date": "10.06",
                "day": "Ср",
                "time": "18:00",
                "duration": 60,
                "service_name": "Персональная",
                "booking_price_cents": None,
                "expected_payment_class": None,
                "arena_name": "Манеж",
                "arena_address": "ул. Тест",
                "booked_for_name": "Лера",
            }
        ],
    )
    assert "Запись для" in reminder
    assert "Лера" in reminder

    moved = msg.format_client_booking_rescheduled_html(
        old_date="10.06",
        old_day="Ср",
        old_time="18:00",
        new_date="11.06",
        new_day="Чт",
        new_time="19:00",
        trainer_name="Мария",
        service_name="Персональная",
        booking_price_cents=None,
        price_tier_label=None,
        arena_name="Манеж",
        arena_address=None,
        duration_minutes=60,
        booked_for_name="Лера",
    )
    assert "Запись для" in moved
    assert "Лера" in moved

    cancelled = msg.format_client_booking_cancelled_html(
        date="10.06",
        day="Ср",
        time="18:00",
        by_trainer=True,
        booked_for_name="Лера",
    )
    assert "Запись для" in cancelled
    assert "Лера" in cancelled


def test_client_confirmed_shows_tickets_hint_and_button_when_url() -> None:
    text = msg.format_client_booking_confirmed_by_trainer_text(
        date="10.06",
        day="Ср",
        time="18:00",
        trainer_name="Мария",
        service_name="Персональная",
        booking_price_cents=None,
        price_tier_label=None,
        arena_name="ТЦ Замок",
        arena_address="ул. Тест",
        arena_tickets_url="https://koronaticket.by/rink",
    )
    assert "ул. Тест\n\n🎟 Билет на лёд лучше взять заранее — онлайн, кнопка ниже.\n" in text
    assert "Остаток" not in text
    kb = msg.build_client_booking_confirmed_inline_keyboard(
        map_url="https://yandex.by/maps/x",
        trainer_telegram_id=1,
        arena_tickets_url="https://koronaticket.by/rink",
        arena_name="ТЦ Замок",
    )
    last = kb.inline_keyboard[-1][0]
    assert last.text == "🎟 Купить билет · ТЦ Замок"
    assert last.url == "https://koronaticket.by/rink"


def test_client_tickets_button_label_falls_back_when_long() -> None:
    assert msg.client_booking_tickets_button_label("Ледовый дворец спорта Минской области") == "🎟 Купить билет"
    assert msg.client_booking_tickets_button_label(None) == "🎟 Купить билет"


def test_client_confirmed_keyboard_unchanged_without_url() -> None:
    with_none = msg.build_client_booking_confirmed_inline_keyboard(
        map_url="https://yandex.by/maps/x", trainer_telegram_id=1, arena_tickets_url=None, arena_name="Зал"
    )
    legacy = msg.build_client_booking_confirmed_inline_keyboard(map_url="https://yandex.by/maps/x", trainer_telegram_id=1)
    assert with_none.model_dump() == legacy.model_dump()


def test_client_confirmed_omits_tickets_without_url() -> None:
    text = msg.format_client_booking_confirmed_by_trainer_text(
        date="10.06",
        day="Ср",
        time="18:00",
        trainer_name="Мария",
        service_name="Персональная",
        booking_price_cents=None,
        price_tier_label=None,
        arena_name="Зал",
        arena_address=None,
        arena_tickets_url=None,
    )
    assert "Билет" not in text


def test_client_reminder_tickets_tomorrow_and_2h() -> None:
    session = {
        "date": "10.06",
        "day": "Ср",
        "time": "18:00",
        "duration": 60,
        "service_name": "Персональная",
        "booking_price_cents": None,
        "expected_payment_class": None,
        "arena_name": "ТЦ Замок",
        "arena_address": "ул. Тест",
        "arena_tickets_url": "https://koronaticket.by/rink",
    }
    tomorrow = msg.format_client_booking_reminder_text(is_soon=False, sessions=[session])
    soon = msg.format_client_booking_reminder_text(is_soon=True, sessions=[session])
    assert "ул. Тест\n\n🎟 Билет на лёд уже есть? Если нет — ещё можно онлайн.\n\nСначала" in tomorrow
    assert f"ул. Тест\n\n{msg.CLIENT_BOOKING_TICKETS_SOON_HINT}\n\nСначала" in soon
    live = msg.format_client_booking_reminder_text(
        is_soon=True, sessions=[{**session, "tickets_free": 41, "tickets_capacity": 115}]
    )
    assert f"{msg.CLIENT_BOOKING_TICKETS_SOON_HINT}\nСейчас свободно 41 из 115.\n\nСначала" in live
    gone = msg.format_client_booking_reminder_text(
        is_soon=True, sessions=[{**session, "tickets_free": 0, "tickets_capacity": 115}]
    )
    assert msg.CLIENT_BOOKING_TICKETS_SOLD_OUT_HINT in gone
    assert "Возьмите сейчас" not in gone


def test_client_reminder_without_url_keeps_blank_line() -> None:
    session = {
        "date": "10.06", "day": "Ср", "time": "18:00", "duration": 60, "service_name": "Персональная",
        "booking_price_cents": None, "expected_payment_class": None, "arena_name": "Зал", "arena_address": "ул. Тест",
    }
    text = msg.format_client_booking_reminder_text(is_soon=False, sessions=[session])
    assert "ул. Тест\n\nСначала" in text
    assert "Билет" not in text


def test_client_reminder_multi_session_tickets_line_once() -> None:
    base = {"date": "10.06", "day": "Ср", "duration": 60, "service_name": "Персональная",
            "booking_price_cents": None, "expected_payment_class": None}
    a = {**base, "time": "10:00", "arena_name": "ТЦ Замок", "arena_tickets_url": "https://koronaticket.by/rink"}
    b = {**base, "time": "18:00", "arena_name": "Зал", "arena_tickets_url": None}
    text = msg.format_client_booking_reminder_text(is_soon=False, sessions=[a, b])
    assert text.count("Билет на лёд уже есть?") == 1
    plain = msg.format_client_booking_reminder_text(is_soon=False, sessions=[{**a, "arena_tickets_url": None}, b])
    assert "Билет" not in plain
    assert "\n\nСначала" in plain


def test_tickets_keyboard_row_dedupes_same_link() -> None:
    rows: list = []
    for _ in range(2):
        msg.append_client_booking_tickets_keyboard_row(rows, arena_tickets_url="https://koronaticket.by/rink", arena_name="ТЦ Замок")
    msg.append_client_booking_tickets_keyboard_row(rows, arena_tickets_url="https://chizhovka-arena.by/x", arena_name="Чижовка")
    assert [r[0].url for r in rows] == ["https://koronaticket.by/rink", "https://chizhovka-arena.by/x"]


def test_trainer_booked_you_has_tickets_line_and_button_only_with_url() -> None:
    kwargs = dict(
        date="25.10", day="Вс", time="21:15", trainer_name="Александр", service_name="Обучение",
        booking_price_cents=None, price_tier_label=None, arena_name="ТЦ Замок",
        arena_address="пр-т Победителей 65", duration_minutes=45, map_link=None,
    )
    text = msg.format_client_trainer_booked_you_html(**kwargs, arena_tickets_url="https://koronaticket.by/rink")
    assert f"пр-т Победителей 65\n\n{msg.CLIENT_BOOKING_TICKETS_CONFIRMED_HINT}\n\nАдрес, отмена" in text
    assert "Билет" not in msg.format_client_trainer_booked_you_html(**kwargs)
    kb = msg.build_client_trainer_booked_you_inline_keyboard(
        booking_id=1, map_url="https://yandex.by/maps", webapp_base_url="https://glideclub.by",
        arena_tickets_url="https://koronaticket.by/rink", arena_name="ТЦ Замок",
    )
    assert kb.inline_keyboard[-1][0].url == "https://koronaticket.by/rink"
    plain = msg.build_client_trainer_booked_you_inline_keyboard(
        booking_id=1, map_url=None, webapp_base_url="https://glideclub.by"
    )
    assert all(getattr(r[0], "url", None) != "https://koronaticket.by/rink" for r in plain.inline_keyboard)


def test_rescheduled_and_recurring_have_tickets_only_with_url() -> None:
    url = "https://koronaticket.by/rink"
    resched = dict(
        old_date="25.10", old_day="Вс", old_time="17:15", new_date="26.10", new_day="Пн", new_time="18:15",
        trainer_name="Александр", service_name="Обучение", booking_price_cents=None, price_tier_label=None,
        arena_name="ТЦ Замок", arena_address="пр-т Победителей 65", duration_minutes=45,
    )
    text = msg.format_client_booking_rescheduled_html(**resched, arena_tickets_url=url)
    assert f"пр-т Победителей 65\n\n{msg.CLIENT_BOOKING_TICKETS_CONFIRMED_HINT}\n\nВсё остальное" in text
    assert "Билет" not in msg.format_client_booking_rescheduled_html(**resched)

    recurring = dict(
        trainer_name="Александр", weekday_short="Пн", time_range="18:15–19:00", service_name="Обучение",
        booking_price_cents=None, price_tier_label=None, arena_display="ТЦ Замок", materialized_count=4,
    )
    text = msg.format_client_recurring_set_by_trainer_notification_html(**recurring, arena_tickets_url=url)
    assert f"📍 <b>Место:</b> ТЦ Замок\n\n{msg.CLIENT_BOOKING_TICKETS_CONFIRMED_HINT}\n\nБлижайшие" in text
    plain = msg.format_client_recurring_set_by_trainer_notification_html(**recurring)
    assert "Билет" not in plain and "📍 <b>Место:</b> ТЦ Замок\n\nБлижайшие" in plain
    kb = msg.build_client_recurring_set_inline_keyboard(
        trainer_telegram_id=5, webapp_base_url="https://glideclub.by", arena_tickets_url=url, arena_name="ТЦ Замок"
    )
    assert kb.inline_keyboard[-1][0].url == url
