"""«Кто кого»: тексты новых уведомлений игрокам (TASK-426, срезы 2–4). Чистые функции, без базы и Telegram.

Формулировки лежат в ``src/shared/copy_ru.json`` (ключи ``kk_notify.*``) и утверждены владельцем 2026-11-16;
здесь только подстановка и типографика: склонения через ``plural_ru``, «во вторник», месяц в родительном
и предложном падеже, порядковые «-м», неразрывные пробелы. Названия команд — в именительном, цифры — числом.

День недели и «сегодня/завтра» считаются на момент отправки (``now`` приходит аргументом), не на момент сборки.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone

from src.application.hockey_teams import display_name as club_name
from src.ingestion.hockey_sources import MINSK_TZ
from src.shared.copy_ru import t
from src.shared.ru_text import plural_ru

NBSP = " "
# Место называем, только если игрок в верхней половине таблицы и участников не меньше 5.
PLACE_MIN_PLAYERS = 5

_PREPOSITION = re.compile(r"(?<![0-9A-Za-zА-Яа-яЁё])(в|во|на|по|у|и|о|из|за|с|со|к|не) ", re.IGNORECASE)
_NUMBER = re.compile(r"(\d(?:-м)?) (?=[А-Яа-яЁё])")


def typo(text: str) -> str:
    """Неразрывные пробелы: после коротких предлогов и частицы «не», между числом и словом, перед тире."""
    text = _PREPOSITION.sub(lambda m: m.group(1) + NBSP, text)
    text = _NUMBER.sub(lambda m: m.group(1) + NBSP, text)
    return text.replace(" —", NBSP + "—")


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MINSK_TZ)


def club_text(name: str) -> str:
    """Название клуба для сообщения (ParseMode.HTML): как в ``club_name``, с экранированием."""
    return html.escape(club_name(name))


def word(kind: str, n: int) -> str:
    return plural_ru(n, t(f"kk_notify.word.{kind}.one"), t(f"kk_notify.word.{kind}.few"), t(f"kk_notify.word.{kind}.many"))


def month_gen(month: int) -> str:
    return t(f"kk_notify.month_gen_{month}")


def month_nom(month: int) -> str:
    return t(f"kk_notify.month_nom_{month}")


def month_prep(month: int) -> str:
    return t(f"kk_notify.month_prep_{month}")


def hhmm(value: datetime) -> str:
    return _local(value).strftime("%H:%M")


def day_phrase(starts_at: datetime, now: datetime) -> str:
    """«сегодня», «завтра», «в субботу» (до шести суток), дальше «3 декабря»."""
    start, today = _local(starts_at), _local(now).date()
    days = (start.date() - today).days
    if days == 0:
        return t("kk_notify.day.today")
    if days == 1:
        return t("kk_notify.day.tomorrow")
    if 2 <= days <= 6:
        return t(f"kk_notify.weekday_{start.weekday()}")
    return t("kk_notify.date", day=start.day, month_gen=month_gen(start.month))


def place_shown(rank: int, size: int) -> bool:
    """Правило места: верхняя половина таблицы и не меньше пяти участников."""
    return size >= PLACE_MIN_PLAYERS and rank * 2 <= size


def match_line(home: str, away: str, starts_at: datetime, now: datetime) -> str:
    return typo(
        t(
            "kk_notify.match",
            home=club_text(home),
            away=club_text(away),
            day=day_phrase(starts_at, now),
            time=hhmm(starts_at),
        )
    )


def _join(*parts: str | None) -> str:
    return "\n".join(p for p in parts if p)


def invite_text(*, home: str, away: str, starts_at: datetime, now: datetime) -> str:
    """Повод 1: матч сегодня или завтра, хода нет."""
    return match_line(home, away, starts_at, now)


def comeback_text(
    *,
    home: str,
    away: str,
    starts_at: datetime,
    now: datetime,
    place_line_text: str | None = None,
) -> str:
    """Повод 2: возврат. ``place_line_text`` — первая строка десятидневного шага, только по правилу места."""
    return _join(place_line_text, match_line(home, away, starts_at, now))


def place_line(*, club: str, month: int, rank: int, size: int) -> str | None:
    if not place_shown(rank, size):
        return None
    return typo(t("kk_notify.place_line", month_gen=month_gen(month), club=club_text(club), rank=rank))


def week_text(
    *,
    moves: int,
    points: int,
    club: str | None,
    month: int,
    rank: int | None,
    size: int | None,
    match: dict | None,
    now: datetime,
) -> str:
    """Повод 3: итог недели. ``match`` — ближайший матч без хода (``home``, ``away``, ``starts_at``) или ``None``."""
    shown = club is not None and rank is not None and size is not None and place_shown(rank, size)
    kw = dict(moves=moves, moves_word=word("move", moves), points=points, points_word=word("point", points))
    if shown:
        head = t("kk_notify.week_place", month_gen=month_gen(month), club=club_text(club), rank=rank, **kw)
    else:
        head = t("kk_notify.week_plain", **kw)
    line = match_line(match["home"], match["away"], match["starts_at"], now) if match else None
    return _join(typo(head), line)


def _exact_clause(exact: int) -> str:
    return t("kk_notify.exact_clause", exact=exact, moves_word=word("move", exact)) if exact >= 1 else ""


def month_text(
    *,
    month: int,
    club: str | None,
    points: int,
    exact: int,
    rank: int | None,
    size: int | None,
    crowned: int,
    i_am_crowned: bool,
    match: dict | None,
    now: datetime,
) -> str:
    """Повод 4: итог месяца. Корона: одному («твоя»), двоим («на двоих»), трём и больше («общая»)."""
    clause = _exact_clause(exact)
    points_word = word("point", points)
    if i_am_crowned and club is not None:
        base = dict(month_nom=month_nom(month), club=club_text(club))
        if crowned <= 1:
            head = t("kk_notify.crown_one", points=points, points_word=points_word, exact_clause=clause, **base)
        elif crowned == 2:
            head = t("kk_notify.crown_two", **base)
        else:
            others = crowned - 1
            head = t("kk_notify.crown_many", n=others, players_word=word("player", others), **base)
    elif club is not None and rank is not None and size is not None and place_shown(rank, size):
        head = t(
            "kk_notify.month_place",
            month_gen=month_gen(month),
            club=club_text(club),
            rank=rank,
            size=size,
            points=points,
            points_word=points_word,
            exact_clause=clause,
        )
    else:
        head = t("kk_notify.month_plain", month_prep=month_prep(month), points=points, points_word=points_word, exact_clause=clause)
    line = match_line(match["home"], match["away"], match["starts_at"], now) if match else None
    return _join(typo(head), line)


def consent_text() -> str:
    return typo(t("kk_notify.consent"))


__all__ = [
    "NBSP",
    "PLACE_MIN_PLAYERS",
    "comeback_text",
    "consent_text",
    "day_phrase",
    "hhmm",
    "invite_text",
    "match_line",
    "month_text",
    "place_line",
    "place_shown",
    "typo",
    "week_text",
    "word",
]
