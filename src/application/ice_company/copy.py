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

# Домашний матч Динамо зовёт друзей тем же движком (TASK-304); тексты у него свои.
MATCH_KIND = "hockey_match"
TOAST_MATCH_MAYBE = "Записали, смотришь дома"
_TOASTS = {
    "g": TOAST_GOING,
    "m": TOAST_MAYBE,
    "x": TOAST_CANT,
}
_MATCH_TOASTS = {**_TOASTS, "m": TOAST_MATCH_MAYBE}
_MONTHS_GEN = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def toast_for(kind: str, action: str) -> str:
    """Тост на нажатие кнопки: у матча «Может» зовётся «Смотрю дома»."""
    table = _MATCH_TOASTS if kind == MATCH_KIND else _TOASTS
    return table.get(action, TOAST_GOING)


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
    # Ответ «может быть». Лёд его в карточке не показывает, матч — «Смотрит дома».
    maybe_names: tuple[str, ...] = ()


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
    if snap.kind == MATCH_KIND:
        if snap.session_cancelled:
            return "Матч отменён"
        if snap.status == "cancelled":
            return "Сбор снят"
        if snap.expired or snap.status == "expired":
            return "Матч прошёл"
        return None
    if snap.session_cancelled:
        return "Сеанс сняли"
    if snap.status == "cancelled":
        return "Сбор снят"
    if snap.expired or snap.status == "expired":
        if len(snap.going_names) >= 2:
            return "Покатались"
        return "Сеанс прошёл"
    return None


def match_when(moment: datetime) -> str:
    """«пт, 23 октября, 19:30»."""
    local = _local(moment)
    return f"{_SHORT[local.weekday()]}, {local.day} {_MONTHS_GEN[local.month - 1]}, {local.strftime('%H:%M')}"


def _names_line(names: tuple[str, ...]) -> str:
    if len(names) <= 5:
        return ", ".join(names)
    return ", ".join(names[:4]) + f" и ещё {len(names) - 4}"


# Компания на матч без своего названия зовётся командами — «Динамо-Минск — СКА» (service.match_title).
MATCH_DEFAULT_PREFIX = "Динамо-Минск — "


def match_nickname(team_title: str | None) -> str:
    """Своё название компании («КУРКУМА») или пусто, если это команды по умолчанию."""
    title = (team_title or "").strip()
    return "" if title.startswith(MATCH_DEFAULT_PREFIX) else title


def match_card_text(snap: Snap) -> str:
    nick = match_nickname(snap.team_title)
    # Своё название — первым словом: в чате его видно сразу. Без него — команды в строке с датой.
    teams = "" if nick else snap.team_title.strip()
    where = " · ".join(part for part in (teams, match_when(snap.starts_at), snap.venue) if part)
    closed = closed_headline(snap)
    if closed:
        return f"{nick + ' · ' if nick else ''}{where}\n{closed}"
    people = []
    if snap.going_names:
        people.append(f"Идут: {_names_line(snap.going_names)}")
    if snap.maybe_names:
        people.append(f"Смотрит дома: {_names_line(snap.maybe_names)}")
    head = f"{nick} — идём на матч?" if nick else "Идём на матч?"
    lines = [head, where]
    if people:
        lines.append(" · ".join(people))
    return "\n".join(lines)


def card_text(snap: Snap) -> str:
    if snap.kind == MATCH_KIND:
        return match_card_text(snap)
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
