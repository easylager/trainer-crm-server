"""Тексты бота. Формулировки из списка приёмки, без восклицаний и без эмодзи."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

MINSK = ZoneInfo("Europe/Minsk")

_IN = ("понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье")
_NOM = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

TOAST_GOING = "Записали, идёшь"
TOAST_MAYBE = "Записали, может быть"
TOAST_CANT = "Записали, не идёшь"
TOAST_QUIET = "Больше не напомним"
TOAST_DEPARTING = "Записали, выезжаешь"
TOAST_ATTENDED = "Записали"
TOAST_CLOSED = "Сбор уже закрыт"
TOAST_RECONFIRM = "Записали, идёшь"


@dataclass(frozen=True)
class Snap:
    kind: str
    venue: str
    starts_at: datetime
    min_people: int
    status: str
    going_names: tuple[str, ...]
    previous_starts_at: datetime | None = None
    cancelled: bool = False
    expired: bool = False


def _local(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=MINSK)
    return moment.astimezone(MINSK)


def weekday_in(moment: datetime) -> str:
    return _IN[_local(moment).weekday()]


def weekday_nom(moment: datetime) -> str:
    return _NOM[_local(moment).weekday()]


def short_when(moment: datetime) -> str:
    local = _local(moment)
    return f"{_SHORT[local.weekday()]} {local.strftime('%H:%M')}"


def clock(moment: datetime) -> str:
    return _local(moment).strftime("%H:%M")


def _names(names: tuple[str, ...]) -> str:
    if not names:
        return ""
    if len(names) <= 8:
        return ", ".join(names)
    head = ", ".join(names[:8])
    return f"{head} и ещё {len(names) - 8}"


def card_text(snap: Snap) -> str:
    when = short_when(snap.starts_at)
    place_line = f"{snap.venue}, {when}"
    if snap.cancelled:
        return f"Сеанс отменён. Вот ближайшие другие\n{place_line}"
    if snap.expired or snap.status == "expired":
        return f"Не состоялась\n{place_line}"
    if snap.status == "cancelled":
        return f"Сбор отменён\n{place_line}"
    if snap.previous_starts_at is not None and snap.status != "confirmed":
        moved = (
            f"Время изменилось: {clock(snap.previous_starts_at)} → {clock(snap.starts_at)}. "
            "Подтвердите ещё раз"
        )
        return f"{moved}\n{place_line}"
    going_n = len(snap.going_names)
    names = _names(snap.going_names)
    if snap.status == "confirmed":
        line = f"Едем. Идут {going_n}: {names}" if names else f"Едем. Идут {going_n}"
        return f"{line}\n{place_line}"
    title = "Катаемся" if snap.kind in ("public_skate", "open_ice") else "Собираемся"
    head = f"{title} в {weekday_in(snap.starts_at)}"
    who = f"Идут {going_n} из {snap.min_people}"
    if names:
        who = f"{who}: {names}"
    lines = [head, place_line, who]
    missing = snap.min_people - going_n
    if missing > 0:
        lines.append(f"Не хватает {missing}")
    return "\n".join(lines)


def confirm_dm(snap: Snap) -> str:
    local = _local(snap.starts_at)
    return f"Сбор готов. {weekday_nom(snap.starts_at)}, {local.strftime('%H:%M')}, {snap.venue}"


def join_dm(name: str) -> str:
    return f"К вам присоединился {name}"


def day_reminder(snap: Snap) -> str:
    return f"Завтра в {clock(snap.starts_at)} {snap.venue}. Идут {len(snap.going_names)}"


def hour_going(snap: Snap) -> str:
    return f"Через час едем. Идут {len(snap.going_names)}"


def hour_maybe(snap: Snap) -> str:
    return f"Идёшь сегодня в {clock(snap.starts_at)}?"


def followup_dm() -> str:
    return "Пока никто не ответил. Поменять время или позвать ещё чат?"


def moved_dm(snap: Snap) -> str:
    assert snap.previous_starts_at is not None
    return (
        f"Время изменилось: {clock(snap.previous_starts_at)} → {clock(snap.starts_at)}. "
        "Подтвердите ещё раз"
    )


def cancel_dm() -> str:
    return "Сеанс отменён. Вот ближайшие другие"


def after_dm() -> str:
    return "Были на льду?"


def weekly_dm(snap: Snap, *, were: int, goal: int) -> str:
    return f"Было {were} из {goal}. Повторить в {weekday_in(snap.starts_at)}?"


def together_line(count: int) -> str:
    n = abs(int(count))
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        word = "раз"
    elif mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        word = "раза"
    else:
        word = "раз"
    return f"Вы катались вместе {n} {word}"
