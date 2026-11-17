"""Прогрев посетителей катков: тексты сообщений и предложения подписки (TASK-428). Чистые функции, без базы и Telegram.

Формулировки — в ``src/shared/copy_ru.json`` (ключи ``warm.*`` и ``watch_offer.*``). Это черновики исполнителя:
до включения флага ``WARM_TEXTS_ACCEPTED`` их принимает владелец. Здесь только подстановка и типографика по
craft-guide: имя катка в ёлочках, время без ведущего нуля у часа, «во вторник», склонения через ``plural_ru``,
неразрывные пробелы (``kk_notify_texts.typo``). Время сеансов — по Минску (все катки каталога в UTC+3).

День («сегодня», «завтра», «в субботу») считается на момент отправки: ``now`` приходит аргументом.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from src.application.ice_watch_message import place_name
from src.application.kk_notify_texts import typo
from src.shared.copy_ru import t
from src.shared.ru_text import plural_ru

MINSK_TZ = ZoneInfo("Europe/Minsk")
# Сколько времён сеансов показываем в одной строке, дальше «и ещё N сеансов».
TIMES_SHOWN = 4
# Сколько дней в недельной подборке.
WEEK_DAYS_SHOWN = 5


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MINSK_TZ)


def arena_title(raw_name: str) -> str:
    """Имя катка для сообщения (HTML-экранировано): в ёлочках, если своих кавычек у имени нет
    («ЛД «Гранд Каньон Айс»» не оборачиваем второй раз)."""
    name = place_name(raw_name)
    return name if "«" in name else f"«{name}»"


def clock(value: time | datetime) -> str:
    """«9:00», «19:30» — без ведущего нуля у часа."""
    if isinstance(value, datetime):
        value = _local(value).time()
    return f"{value.hour}:{value.minute:02d}"


def session_word(n: int) -> str:
    return plural_ru(n, t("warm.word.session.one"), t("warm.word.session.few"), t("warm.word.session.many"))


def times_phrase(starts: list[datetime]) -> str:
    """«19:30», «12:00 и 19:30», «9:00, 12:00, 15:30, 17:00 и ещё 2 сеанса»."""
    shown = [clock(s) for s in starts[:TIMES_SHOWN]]
    rest = len(starts) - len(shown)
    if rest > 0:
        return ", ".join(shown) + " " + t("warm.more", n=rest, word=session_word(rest))
    if len(shown) == 1:
        return shown[0]
    return ", ".join(shown[:-1]) + " и " + shown[-1]


def day_phrase(day: date, today: date) -> str:
    """«сегодня», «завтра», «в субботу» (до шести суток), дальше «22 ноября»."""
    days = (day - today).days
    if days == 0:
        return t("kk_notify.day.today")
    if days == 1:
        return t("kk_notify.day.tomorrow")
    if 2 <= days <= 6:
        return t(f"kk_notify.weekday_{day.weekday()}")
    return t("kk_notify.date", day=day.day, month_gen=t(f"kk_notify.month_gen_{day.month}"))


def when_phrase(starts_at: datetime, now: datetime) -> str:
    """«завтра в 12:00», «в субботу в 15:30»."""
    local = _local(starts_at)
    return f"{day_phrase(local.date(), _local(now).date())} в {clock(local)}"


def _future(starts: list[datetime], now: datetime) -> list[datetime]:
    return sorted(s for s in starts if _local(s) > _local(now))


def welcome_text(*, arena_name: str, starts: list[datetime], now: datetime) -> str | None:
    """После подписки: ближайшие 1–2 сеанса одной строкой. Подтверждение подписки уже прислал бот (``/start watch_…``,
    кнопка напоминания) или показал Mini App, поэтому здесь его не повторяем и ничего не обещаем. Сеансов нет — ``None``.
    """
    upcoming = _future(starts, now)[:2]
    arena = arena_title(arena_name)
    if len(upcoming) == 1:
        return typo(t("warm.next_one", arena=arena, first=when_phrase(upcoming[0], now)))
    if len(upcoming) == 2:
        return typo(
            t("warm.next_two", arena=arena, first=when_phrase(upcoming[0], now), second=when_phrase(upcoming[1], now))
        )
    return None


def today_text(*, arena_name: str, starts: list[datetime], now: datetime) -> str | None:
    """Утром в день сеанса: «Сегодня на катке «…» лёд в 12:00 и 19:30.» Ничего впереди — ``None``."""
    today = _local(now).date()
    left = [s for s in _future(starts, now) if _local(s).date() == today]
    if not left:
        return None
    return typo(t("warm.today", arena=arena_title(arena_name), times=times_phrase(left)))


def week_text(*, arena_name: str, starts: list[datetime], now: datetime) -> str | None:
    """Подборка на неделю: строка на день, не больше ``WEEK_DAYS_SHOWN`` дней. Нечего показать — ``None``."""
    by_day: dict[date, list[datetime]] = {}
    for s in _future(starts, now):
        by_day.setdefault(_local(s).date(), []).append(s)
    if not by_day:
        return None
    today = _local(now).date()
    lines = [f"<b>{t('warm.week_head', arena=arena_title(arena_name))}</b>"]
    for day in sorted(by_day)[:WEEK_DAYS_SHOWN]:
        lines.append("• " + t("warm.week_line", day=day_phrase(day, today), times=times_phrase(by_day[day])))
    return typo("\n".join(lines))


def nudge_text(*, arena_name: str) -> str:
    """Единственное напоминание тому, кто запускал бота и смотрел каток, но не подписан."""
    return typo(t("warm.nudge", arena=arena_title(arena_name)))


__all__ = [
    "arena_title",
    "clock",
    "day_phrase",
    "nudge_text",
    "session_word",
    "times_phrase",
    "today_text",
    "week_text",
    "welcome_text",
    "when_phrase",
]
