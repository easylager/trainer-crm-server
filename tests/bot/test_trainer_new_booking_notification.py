"""Тренеру о новой записи — полная карточка со всеми данными (как до TASK-314)."""

from datetime import date, time

from src.bot import messages as msg


def _text(**over):
    kw = dict(
        client_name="Мария Ковальчук",
        phone="+375 29 123-45-67",
        slot_date=date(2026, 10, 23),
        start_time=time(17, 15),
        end_time=time(18, 0),
        duration_minutes=45,
        service="Фигурное катание",
        tariff="Ребёнок",
        price="45\u00a0BYN",
        city="Минск",
        arena="Замок",
        comment="Дочь, 7 лет",
        first_online=False,
    )
    kw.update(over)
    return msg.format_trainer_new_booking_html(**kw)


def test_full_card_has_every_field() -> None:
    t = _text()
    assert t.startswith("🔔 <b>Новая запись</b> — нужно ваше решение")
    assert "👤 <b>ФИО:</b> Мария Ковальчук" in t
    assert "📞 +375 29 123-45-67" in t
    assert "📅 <b>23.10 (Пт) 17:15–18:00</b> — 45 мин." in t
    assert "🎯 Фигурное катание" in t
    assert "💳 <b>Тариф:</b> Ребёнок · 45\u00a0BYN" in t
    assert "📍 Минск · 🏟 Замок" in t
    assert "💬 <b>Комментарий:</b> Дочь, 7 лет" in t
    assert "подтвердите, отклоните или напишите клиенту" in t


def test_empty_fields_are_skipped_not_dashed() -> None:
    t = _text(phone=None, comment=" ", tariff=None, price="", city="—", arena="—", service="—")
    assert "📞" not in t and "💬" not in t and "💳" not in t and "📍" not in t and "🎯" not in t
    assert "—\n" not in t


def test_first_online_booking_prefix_and_escaping() -> None:
    t = _text(first_online=True, client_name="<b>x</b>")
    assert t.startswith("✨ <b>Первая онлайн-запись</b>")
    assert "&lt;b&gt;x&lt;/b&gt;" in t
