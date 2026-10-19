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
TOAST_CLOSED = "Сбор уже закрыт"


@dataclass(frozen=True)
class Snap:
    kind: str
    venue: str
    starts_at: datetime
    status: str
    going_names: tuple[str, ...]
    team_title: str = ""
    session_cancelled: bool = False
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


def crowd_line(going: int) -> str:
    n = max(0, int(going))
    if n == 0:
        return "Лёд пока пустой"
    if n == 1:
        return "Пока один. Одному можно, но вдвоём веселее"
    if n == 2:
        return "Двое — это уже не катание, а свидание"
    if n == 3:
        return "Трое — это уже компания"
    if n == 4:
        return "Четверо — можно два на два"
    if n == 5:
        return "Пятеро — готовая хоккейная пятёрка"
    if n == 6:
        return "Шестеро — пятёрка и вратарь"
    if n == 7:
        return "Семеро — каток, считай, ваш"
    if n == 8:
        return "Восьмеро — каток, считай, ваш"
    if n == 9:
        return "Девятеро — каток, считай, ваш"
    return f"{n} человек — это уже не компания, а выезд"


def on_the_ice(names: tuple[str, ...]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return f"На льду {names[0]}"
    if len(names) == 2:
        return f"На льду {names[0]} и {names[1]}"
    if len(names) <= 4:
        return "На льду " + ", ".join(names[:-1]) + " и " + names[-1]
    return f"На льду {names[0]}, {names[1]} и ещё {len(names) - 2}"


def closed_headline(snap: Snap) -> str | None:
    if snap.session_cancelled:
        return "Сеанс сняли"
    if snap.status == "cancelled":
        return "Сбор снят"
    if snap.expired or snap.status == "expired":
        if len(snap.going_names) >= 2:
            return "Покатались"
        return "Сеанс прошёл"
    return None


def card_text(snap: Snap) -> str:
    when = f"{weekday_nom(snap.starts_at)}, {clock(snap.starts_at)}"
    place = snap.venue
    label = kind_label(snap.kind)
    team = (snap.team_title or "").strip()
    team_line = f"{team}\n" if team else ""
    head = f"{label}\n" if label else ""
    closed = closed_headline(snap)
    if closed:
        return f"{head}{team_line}{closed}\n{when}\n{place}"
    who = on_the_ice(snap.going_names)
    lines = [head.rstrip("\n"), team_line.rstrip("\n"), when, place]
    if who:
        lines.append(f"{who}.")
    lines.append(crowd_line(len(snap.going_names)))
    return "\n".join(part for part in lines if part)
