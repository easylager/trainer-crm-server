"""Короткий текст про катки в чате клиентского бота — это поисковый запрос, а не обращение.

Люди пишут боту как в поисковик («Минск Массовое Катание»). Такой текст ведём в Mini App,
в поддержку он не идёт. Без ИИ: корни слов плюс названия городов из БД.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable

#: Дольше — это описание проблемы, а не запрос: остаётся обращением.
RINK_QUERY_MAX_LEN = 60

#: Корни, с начала слова: ловят падежи и формы («катка», «катании», «хоккейный»). ``ё`` → ``е`` заранее.
RINK_ROOTS = (
    "каток",
    "катк",
    "катан",
    "лед",
    "хокке",
    "фигурн",
    "коньк",
    "прокат",
    "заточ",
    "сеанс",
    "расписан",
)

_ROOTS_RE = re.compile(r"(?<![а-яa-z0-9])(?:" + "|".join(RINK_ROOTS) + ")", re.IGNORECASE)

_CITY_TTL_SECONDS = 600.0
_city_cache: tuple[float, tuple[str, ...]] | None = None


def _norm(value: str) -> str:
    return (value or "").lower().replace("ё", "е")


def _city_stem(name: str) -> str:
    """«Минск» → «минск», «Гомель» → «гомел»: окончание падежа не мешает совпадению."""
    n = _norm(name).strip()
    return n[:-1] if len(n) >= 6 else n


def build_city_regex(city_names: Iterable[str]) -> re.Pattern[str] | None:
    stems = sorted({s for s in (_city_stem(n) for n in city_names) if len(s) >= 3}, key=len, reverse=True)
    if not stems:
        return None
    return re.compile(r"(?<![а-яa-z0-9])(?:" + "|".join(re.escape(s) for s in stems) + ")", re.IGNORECASE)


def is_rink_query(text: str | None, city_names: Iterable[str] = ()) -> bool:
    """True для короткого текста с корнем «катки/лёд/хоккей…» или названием города."""
    raw = (text or "").strip()
    if not raw or len(raw) > RINK_QUERY_MAX_LEN or raw.startswith("/"):
        return False
    t = _norm(raw)
    if _ROOTS_RE.search(t):
        return True
    cities = build_city_regex(city_names)
    return bool(cities and cities.search(t))


async def known_city_names(session) -> tuple[str, ...]:
    """Имена активных городов из БД, кэш на 10 минут. Сбой БД → пусто (остаются только корни)."""
    global _city_cache
    now = time.monotonic()
    if _city_cache and now - _city_cache[0] < _CITY_TTL_SECONDS:
        return _city_cache[1]
    from sqlalchemy import text as sql

    try:
        rows = (await session.execute(sql("SELECT name FROM cities WHERE is_active"))).all()
        names = tuple(str(r[0]) for r in rows if r and r[0])
    except Exception:  # noqa: BLE001
        return ()
    _city_cache = (now, names)
    return names


def reset_city_cache() -> None:
    global _city_cache
    _city_cache = None
