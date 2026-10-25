from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from src.application.booking_tickets_push import (
    BookedTicket,
    format_low_tickets_text,
    format_trainer_forward_card,
    format_trainer_forward_intro,
    is_low,
    match_session_free,
    trainer_forward_due,
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


def test_trainer_forward_texts_escape_and_list_clients() -> None:
    intro = format_trainer_forward_intro(
        [_booked(date(2026, 10, 25), time(15, 15), "Аня <b>"), _booked(date(2026, 10, 24), time(18, 15))],
        today=date(2026, 10, 24),
    )
    assert "• Аня &lt;b&gt; — завтра 15:15, ТЦ Замок" in intro
    assert "• Анна — сегодня 18:15, ТЦ Замок" in intro
    card = format_trainer_forward_card(
        arena_name="ТЦ Замок", tickets_url="https://koronaticket.by/rink", client_bot_username="@glide_bot"
    )
    assert "«ТЦ Замок»" in card
    assert "https://koronaticket.by/rink" in card
    assert card.endswith("— @glide_bot")
    assert "@" not in format_trainer_forward_card(
        arena_name="ТЦ Замок", tickets_url="https://koronaticket.by/rink", client_bot_username=None
    )
