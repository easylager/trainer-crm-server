"""Render a care pulse as Telegram HTML. Templates live in ``messages.py``."""
from __future__ import annotations

import html as html_lib
from datetime import date, time
from typing import Any

from src.bot import messages as msg
from src.infrastructure.db.models import (
    CARE_PULSE_AUDIENCE_CLIENT,
    CARE_PULSE_AUDIENCE_TRAINER,
    CARE_PULSE_KIND_CONFIRMED_BOOKING,
    CARE_PULSE_KIND_INVITE_BACK,
    CARE_PULSE_KIND_OPEN_SLOTS,
    CARE_PULSE_KIND_QUIET_CHECKIN,
    CARE_PULSE_KIND_TOMORROW_PLAN,
)

_WEEKDAY_IN = (
    "В понедельник",
    "Во вторник",
    "В среду",
    "В четверг",
    "В пятницу",
    "В субботу",
    "В воскресенье",
)


def _h(text: str) -> str:
    return html_lib.escape(text or "", quote=False)


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return few
    return many


def _sessions_word(n: int) -> str:
    return _plural_ru(n, "тренировка", "тренировки", "тренировок")


def _windows_word(n: int) -> str:
    return _plural_ru(n, "окно", "окна", "окон")


def _days_word(n: int) -> str:
    return _plural_ru(n, "день", "дня", "дней")


def _fmt_time(value: Any) -> str:
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if value is None:
        return ""
    text_v = str(value)
    return text_v[:5] if len(text_v) >= 5 else text_v


def _short_name(full_name: str) -> str:
    parts = (full_name or "").split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1][:1]}."
    return (full_name or "").strip()


def _weekday_in(slot_date: date | None) -> str:
    if slot_date is None:
        return ""
    return _WEEKDAY_IN[slot_date.weekday()]


def format_care_pulse_html(*, audience: str, kind: str, payload: dict[str, Any]) -> str | None:
    if audience == CARE_PULSE_AUDIENCE_TRAINER:
        return _format_trainer(kind, payload)
    if audience == CARE_PULSE_AUDIENCE_CLIENT:
        return _format_client(kind, payload)
    return None


def _format_trainer(kind: str, payload: dict[str, Any]) -> str | None:
    if kind == CARE_PULSE_KIND_TOMORROW_PLAN:
        n = int(payload.get("sessions_count") or 0)
        first = _fmt_time(payload.get("first_time"))
        name = _short_name(str(payload.get("first_name") or ""))
        return msg.CARE_PULSE_TRAINER_TOMORROW.format(
            count=n,
            word=_sessions_word(n),
            first_time=_h(first) if first else "—",
            first_name=_h(name) if name else "—",
        )
    if kind == CARE_PULSE_KIND_OPEN_SLOTS:
        n = int(payload.get("open_slots") or 0)
        return msg.CARE_PULSE_TRAINER_OPEN_SLOTS.format(
            count=n,
            word=_windows_word(n),
        )
    if kind == CARE_PULSE_KIND_INVITE_BACK:
        name = _short_name(str(payload.get("name") or "")) or "Клиент"
        days = int(payload.get("days") or 0)
        return msg.CARE_PULSE_TRAINER_INVITE_BACK.format(
            name=_h(name),
            days=days,
            word=_days_word(days),
        )
    if kind == CARE_PULSE_KIND_QUIET_CHECKIN:
        return msg.CARE_PULSE_TRAINER_QUIET
    return None


def _format_client(kind: str, payload: dict[str, Any]) -> str | None:
    if kind == CARE_PULSE_KIND_CONFIRMED_BOOKING:
        slot_date = payload.get("slot_date")
        day_name = _weekday_in(slot_date if isinstance(slot_date, date) else None)
        date_str = slot_date.strftime("%d.%m") if isinstance(slot_date, date) else ""
        when = f"{date_str}" if date_str else "Скоро"
        # Remove "В " prefix for day name (e.g. "В пятницу" -> "пятницу")
        day_display = day_name.replace("В ", "").lower() if day_name else ""
        clock = _fmt_time(payload.get("start_time"))
        trainer = str(payload.get("trainer_name") or "").strip()
        arena = str(payload.get("arena_name") or "").strip()
        arena_line = f"📍 {_h(arena)}\n" if arena else ""
        duration = payload.get("duration_minutes", 45)

        return msg.CARE_PULSE_CLIENT_CONFIRMED.format(
            when=_h(when),
            day_name=_h(day_display),
            time=_h(clock) if clock else "—",
            duration=int(duration) if duration else 45,
            trainer_name=_h(trainer) if trainer else "Тренер",
            arena_line=arena_line,
        )
    if kind == CARE_PULSE_KIND_INVITE_BACK:
        trainer = str(payload.get("trainer_name") or "").strip()
        return msg.CARE_PULSE_CLIENT_INVITE_BACK.format(
            trainer_name=_h(trainer) if trainer else "Тренер"
        )
    return None
