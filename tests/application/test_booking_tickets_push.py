from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from src.application.booking_tickets_push import (
    BookedTicket,
    format_low_tickets_text,
    format_trainer_forward_text,
    is_low,
    match_session_free,
    trainer_forward_due,
    trainer_forward_markup,
)

MINSK = ZoneInfo("Europe/Minsk")


def _booked(slot_date: date, start: time, name: str = "Анна") -> BookedTicket:
    return BookedTicket(
        booking_id=1,
        client_id=2,
        trainer_id=9,
        slot_date=slot_date,
        start_time=start,
        arena_id=3,
        arena_name="ТЦ Замок",
        tickets_url="https://koronaticket.by/rink",
        client_name=name,
        trainer_telegram_id=100,
    )


def test_match_session_covers_booking_start_within_the_hour() -> None:
    snaps = {3: [(time(16, 15), 115, 60), (time(17, 15), 115, 20)]}
    assert match_session_free(snaps, 3, time(17, 15)) == (20, 115)
    assert match_session_free(snaps, 3, time(17, 45)) == (20, 115)
    assert match_session_free(snaps, 3, time(16, 45)) == (60, 115)
    assert match_session_free(snaps, 3, time(15, 0)) is None
    assert match_session_free(snaps, 5, time(17, 15)) is None


def test_is_low_half_sold_but_not_sold_out() -> None:
    assert is_low(57, 115)
    assert not is_low(58, 115)
    assert not is_low(0, 115)


def test_trainer_forward_tomorrow_from_evening_today_with_an_hour_left() -> None:
    today = date(2026, 10, 24)
    tomorrow = _booked(date(2026, 10, 25), time(15, 15))
    later_today = _booked(today, time(17, 15))
    assert not trainer_forward_due(tomorrow, datetime(2026, 10, 24, 18, 59, tzinfo=MINSK))
    assert trainer_forward_due(tomorrow, datetime(2026, 10, 24, 19, 0, tzinfo=MINSK))
    assert trainer_forward_due(later_today, datetime(2026, 10, 24, 16, 15, tzinfo=MINSK))
    assert not trainer_forward_due(later_today, datetime(2026, 10, 24, 16, 16, tzinfo=MINSK))
    assert not trainer_forward_due(
        _booked(date(2026, 10, 26), time(15, 15)), datetime(2026, 10, 24, 20, 0, tzinfo=MINSK)
    )


def test_low_tickets_text() -> None:
    text = format_low_tickets_text(arena_name="ТЦ Замок", start=time(17, 15), free=23, capacity=115)
    assert "Билеты на ваш сеанс заканчиваются" in text
    assert "Сегодня · 17:15 · ТЦ Замок" in text
    assert "Свободно 23 из 115." in text


def test_trainer_forward_one_message_with_share_buttons() -> None:
    from urllib.parse import parse_qs, urlparse

    today = date(2026, 10, 24)
    rows = [_booked(date(2026, 10, 25), time(13, 15), "Татьяна <b>"), _booked(today, time(18, 15), "Анна Ли")]
    text = format_trainer_forward_text(rows, today=today)
    assert "Татьяна &lt;b&gt; — завтра 13:15, ТЦ Замок" in text
    assert "Анна Ли — сегодня 18:15, ТЦ Замок" in text
    assert "У этих учеников нет нашего бота" in text
    markup = trainer_forward_markup(rows, today=today)
    labels = [r[0].text for r in markup.inline_keyboard]
    assert labels == ["📤 Татьяна · 13:15", "📤 Анна · 18:15"]
    q = parse_qs(urlparse(markup.inline_keyboard[1][0].url).query)
    assert q["url"] == ["https://koronaticket.by/rink"]
    assert q["text"][0].startswith("Анна, напоминаю: сегодня в 18:15 занятие на катке «ТЦ Замок».")
    single = trainer_forward_markup(rows[:1], today=today)
    assert single.inline_keyboard[0][0].text == "📤 Отправить напоминание"
    assert "У ученика нет нашего бота" in format_trainer_forward_text(rows[:1], today=today)
