"""Care pulse Telegram renderer — structure and calm voice, not exact copy freeze."""
from datetime import date, time

from src.bot.care_pulse_format import format_care_pulse_html
from src.infrastructure.db.models import (
    CARE_PULSE_AUDIENCE_CLIENT,
    CARE_PULSE_AUDIENCE_TRAINER,
    CARE_PULSE_KIND_CONFIRMED_BOOKING,
    CARE_PULSE_KIND_INVITE_BACK,
    CARE_PULSE_KIND_OPEN_SLOTS,
    CARE_PULSE_KIND_QUIET_CHECKIN,
    CARE_PULSE_KIND_TOMORROW_PLAN,
)


def test_trainer_tomorrow_mentions_count_and_time():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_TRAINER,
        kind=CARE_PULSE_KIND_TOMORROW_PLAN,
        payload={
            "sessions_count": 2,
            "first_time": time(18, 0),
            "first_name": "Анна Смирнова",
        },
    )
    assert text is not None
    assert "🌿" in text
    assert "2" in text
    assert "Первая" in text
    assert "18:00" in text
    assert "Анна" in text
    assert "👉" not in text


def test_trainer_tomorrow_one_session_no_pervaya():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_TRAINER,
        kind=CARE_PULSE_KIND_TOMORROW_PLAN,
        payload={
            "sessions_count": 1,
            "first_time": time(10, 30),
            "first_name": "Игорь",
        },
    )
    assert text is not None
    assert "1" in text
    assert "тренировка в" in text
    assert "Первая" not in text
    assert "тренировка." not in text
    assert "10:30" in text


def test_trainer_open_slots_no_double_okon():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_TRAINER,
        kind=CARE_PULSE_KIND_OPEN_SLOTS,
        payload={"open_slots": 5},
    )
    assert text is not None
    assert "5" in text
    assert text.lower().count("окон") == 1


def test_trainer_invite_escapes_html():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_TRAINER,
        kind=CARE_PULSE_KIND_INVITE_BACK,
        payload={"name": "Игорь <script>", "days": 19},
    )
    assert text is not None
    assert "&lt;" in text
    assert "<script>" not in text


def test_trainer_quiet():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_TRAINER,
        kind=CARE_PULSE_KIND_QUIET_CHECKIN,
        payload={},
    )
    assert text is not None
    assert "Расписание на месте" in text


def test_client_confirmed():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_CLIENT,
        kind=CARE_PULSE_KIND_CONFIRMED_BOOKING,
        payload={
            "slot_date": date(2026, 8, 20),  # Thursday
            "start_time": time(18, 0),
            "trainer_name": "Максим",
            "arena_name": "Минск-Арена",
        },
    )
    assert text is not None
    assert text.split("\n\n")[1].startswith("В четверг")
    assert "18:00" in text
    assert "тренер Максим" in text
    assert "к Максим" not in text
    assert "Минск-Арена" in text


def test_client_invite_back_nominative_label():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_CLIENT,
        kind=CARE_PULSE_KIND_INVITE_BACK,
        payload={"trainer_name": "Максим"},
    )
    assert text is not None
    assert "Тренер: <b>Максим</b>" in text
    assert "к Максим" not in text
    assert "каталог" in text.lower()
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_TRAINER,
        kind=CARE_PULSE_KIND_TOMORROW_PLAN,
        payload={
            "sessions_count": 2,
            "first_time": time(18, 0),
            "first_name": "Анна Смирнова",
        },
    )
    assert text is not None
    assert "🌿" in text
    assert "2" in text
    assert "18:00" in text
    assert "Анна" in text
    assert "👉" not in text


def test_trainer_open_slots_escapes_nothing_needed():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_TRAINER,
        kind=CARE_PULSE_KIND_OPEN_SLOTS,
        payload={"open_slots": 5},
    )
    assert text is not None
    assert "5" in text


def test_trainer_invite_escapes_html():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_TRAINER,
        kind=CARE_PULSE_KIND_INVITE_BACK,
        payload={"name": "Игорь <script>", "days": 19},
    )
    assert text is not None
    assert "&lt;" in text
    assert "<script>" not in text


def test_trainer_quiet():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_TRAINER,
        kind=CARE_PULSE_KIND_QUIET_CHECKIN,
        payload={},
    )
    assert text is not None
    assert "на месте" in text.lower() or "Расписание" in text


def test_client_confirmed():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_CLIENT,
        kind=CARE_PULSE_KIND_CONFIRMED_BOOKING,
        payload={
            "slot_date": date(2026, 8, 20),  # Thursday
            "start_time": time(18, 0),
            "trainer_name": "Максим",
            "arena_name": "Минск-Арена",
        },
    )
    assert text is not None
    assert "четверг" in text
    assert "18:00" in text
    assert "Максим" in text
    assert "Минск-Арена" in text


def test_client_invite_back():
    text = format_care_pulse_html(
        audience=CARE_PULSE_AUDIENCE_CLIENT,
        kind=CARE_PULSE_KIND_INVITE_BACK,
        payload={"trainer_name": "Максим"},
    )
    assert text is not None
    assert "Максим" in text
    assert "каталог" in text.lower()
