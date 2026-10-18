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
    team_title: str = ""
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


_KIND_LABELS = {
    "public_skate": "Массовое катание",
    "open_ice": "Массовое катание",
    "hockey_practice": "ОХМ",
}


def kind_label(kind: str) -> str:
    """Что это за сеанс. Пустая строка — тип ещё не назван, на карточку не выдумываем."""
    return _KIND_LABELS.get(kind, "")


_STILL = {1: "один", 2: "двое", 3: "трое", 4: "четверо", 5: "пятеро", 6: "шестеро", 7: "семеро"}


def on_the_ice(names: tuple[str, ...]) -> str:
    if not names:
        return "Лёд ещё пустой"
    if len(names) == 1:
        return f"На льду {names[0]}"
    if len(names) == 2:
        return f"На льду {names[0]} и {names[1]}"
    if len(names) <= 4:
        return "На льду " + ", ".join(names[:-1]) + " и " + names[-1]
    return f"На льду {names[0]}, {names[1]} и ещё {len(names) - 2}"


def still_line(missing: int) -> str:
    word = _STILL.get(missing)
    if word:
        return f"Ещё {word} — и едем"
    return f"Ещё {missing} — и едем"


def team_gathered(snap: Snap) -> bool:
    if snap.cancelled or snap.expired or snap.status in ("cancelled", "expired"):
        return False
    return snap.status == "confirmed" or len(snap.going_names) >= snap.min_people


def card_text(snap: Snap) -> str:
    when = f"{weekday_nom(snap.starts_at)}, {clock(snap.starts_at)}"
    place = snap.venue
    label = kind_label(snap.kind)
    team = (snap.team_title or "").strip()
    team_line = f"{team}\n" if team else ""
    head = f"{label}\n" if label else ""
    if snap.cancelled:
        return f"{head}{team_line}Сеанс сняли.\n{when}\n{place}"
    if snap.expired or snap.status == "expired":
        return f"{head}{team_line}Не собрались.\n{when}\n{place}"
    if snap.status == "cancelled":
        return f"{head}{team_line}Сбор снят.\n{when}\n{place}"
    if snap.previous_starts_at is not None and snap.status != "confirmed":
        return (
            f"{head}{team_line}Время съехало: {clock(snap.previous_starts_at)} → {clock(snap.starts_at)}.\n"
            "Подтвердите ещё раз.\n"
            f"{place}"
        )
    who = on_the_ice(snap.going_names) + "."
    if team_gathered(snap):
        return f"{head}{team_line}Едем.\n{when}\n{place}\n{who}"
    missing = snap.min_people - len(snap.going_names)
    return f"{head}{team_line}{when}\n{place}\n{who}\n{still_line(missing)}"


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
