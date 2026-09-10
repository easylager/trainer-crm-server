"""
«Лёд сегодня в городе» — публичный шеринг-артефакт эпика client-premium (TASK-096, DEC-004).

Что здесь важно понимать про продукт: люди не пересылают друг другу приложения, они
пересылают полезную информацию. «Расписание всего льда Минска на сегодня с ценами» —
это то, что кидают в родительский чат; «установи наше приложение» — нет. Поэтому
артефакт живёт на публичной странице **без авторизации**: получатель ссылки не должен
ставить бота, чтобы увидеть, ради чего ему прислали ссылку.

Данные ровно те же, что видит вкладка «Лёд»: ``ice_sessions`` со статусом active,
kind ``public_skate|open_ice``, ещё не начавшиеся (``starts_at_utc > now``, PDEC-005).
Ничего не досочиняется — ни рейтингов, ни «осталось 3 места» (AC-005).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_profile import ARENA_PROFILE_STATUS_PUBLISHED
from src.application.ice_session_use_cases import STATUS_ACTIVE

DEFAULT_TIMEZONE = "Europe/Minsk"

# Кириллица → латиница для slug города. Таблица короткая осознанно: в БД у городов нет
# колонки slug, и заводить миграцию ради ЧПУ-адреса дороже, чем транслитерировать имя.
_TRANSLIT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "і": "i", "ў": "u", "ґ": "g", "є": "e", "ї": "yi",
}


def city_slug(name: str) -> str:
    """
    ``«Минск» → "minsk"``, ``«Санкт-Петербург» → "sankt-peterburg"``.

    Детерминированная функция от имени: slug нигде не хранится, он каждый раз выводится.
    Значит переименование города меняет и адрес — старые ссылки перестанут открываться.
    Это осознанный размен: колонка ``cities.slug`` с миграцией и админкой не окупается,
    пока городов десятки, а переименований не было ни одного.
    """
    out: list[str] = []
    for ch in (name or "").strip().lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        else:
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


async def resolve_city_by_ref(session: AsyncSession, city_ref: str) -> dict[str, Any] | None:
    """Город по slug (``minsk``) или по числовому id. ``None`` — если такого города нет."""
    ref = (city_ref or "").strip()
    if not ref:
        return None
    result = await session.execute(
        text("SELECT id, name, country FROM cities WHERE is_active ORDER BY sort_order, id")
    )
    rows = result.mappings().all()
    if ref.isdigit():
        wanted_id = int(ref)
        for row in rows:
            if int(row["id"]) == wanted_id:
                return dict(row)
        return None
    wanted = ref.lower()
    for row in rows:
        if city_slug(str(row["name"])) == wanted:
            return dict(row)
    return None


async def _city_timezone(session: AsyncSession, city_id: int) -> str:
    """Часовой пояс города = пояс любой его арены. У городов своей колонки нет."""
    row = (
        await session.execute(
            text(
                """
                SELECT p.timezone
                FROM arenas a
                JOIN arena_profiles p ON p.arena_id = a.id
                WHERE a.city_id = :cid AND a.is_active AND p.timezone IS NOT NULL
                ORDER BY a.id
                LIMIT 1
                """
            ),
            {"cid": int(city_id)},
        )
    ).first()
    return (row[0] if row and row[0] else None) or DEFAULT_TIMEZONE


def _local_today(tz_name: str) -> date:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — битый пояс в профиле не должен ронять публичную страницу
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.now(tz).date()


_DAY_SQL = """
SELECT
    a.id            AS arena_id,
    a.name          AS arena_name,
    a.address       AS address,
    p.slug          AS arena_slug,
    p.district      AS district,
    s.id            AS session_id,
    s.kind          AS kind,
    s.starts_at_local,
    s.ends_at_local,
    s.price_adult_minor,
    s.price_child_minor,
    s.price_rental_minor,
    s.currency_code,
    s.price_note,
    s.session_label,
    s.age_note
FROM ice_sessions s
JOIN arenas a ON a.id = s.arena_id
LEFT JOIN arena_profiles p ON p.arena_id = a.id
WHERE a.city_id = :cid
  AND a.is_active AND a.is_confirmed
  AND (p.status IS NULL OR p.status = :published)
  AND s.status = :st
  AND s.kind IN ('public_skate', 'open_ice')
  AND s.local_date = :day
  AND s.starts_at_utc > :now
  AND (s.valid_until IS NULL OR s.valid_until >= :now)
ORDER BY a.name, s.starts_at_local, s.id
"""


def _hhmm(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "hour"):
        return f"{value.hour:02d}:{value.minute:02d}"
    return str(value)[:5]


def format_price_minor(minor: int | None, currency: str) -> str:
    """``850, "BYN"`` → ``"8.50 BYN"``. ``None`` → пустая строка, а не «0»."""
    if minor is None:
        return ""
    major = int(minor) / 100.0
    if major == int(major):
        return f"{int(major)} {currency}"
    return f"{major:.2f} {currency}"


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    n_abs = abs(int(n)) % 100
    if 11 <= n_abs <= 14:
        return many
    last = n_abs % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


_MONTHS_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def human_date(day: date, *, today: date) -> str:
    if day == today:
        return "сегодня"
    if day == today + timedelta(days=1):
        return "завтра"
    return f"{day.day} {_MONTHS_GEN[day.month - 1]}"


async def _load_day(
    session: AsyncSession, *, city_id: int, day: date, now: datetime
) -> list[Mapping[str, Any]]:
    result = await session.execute(
        _DAY_SQL_TEXT,
        {
            "cid": int(city_id),
            "day": day,
            "now": now,
            "st": STATUS_ACTIVE,
            "published": ARENA_PROFILE_STATUS_PUBLISHED,
        },
    )
    return list(result.mappings().all())


_DAY_SQL_TEXT = text(_DAY_SQL)


def _group_by_arena(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    arenas: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for row in rows:
        aid = int(row["arena_id"])
        if aid not in arenas:
            arenas[aid] = {
                "arena_id": aid,
                "name": row["arena_name"],
                "slug": row["arena_slug"],
                "district": row["district"],
                "address": row["address"],
                "sessions": [],
            }
            order.append(aid)
        currency = row["currency_code"] or "BYN"
        arenas[aid]["sessions"].append(
            {
                "session_id": int(row["session_id"]),
                "kind": row["kind"],
                "starts_at_local": _hhmm(row["starts_at_local"]),
                "ends_at_local": _hhmm(row["ends_at_local"]),
                "price_adult_minor": row["price_adult_minor"],
                "price_child_minor": row["price_child_minor"],
                "price_rental_minor": row["price_rental_minor"],
                "currency_code": currency,
                "price_adult": format_price_minor(row["price_adult_minor"], currency),
                "price_child": format_price_minor(row["price_child_minor"], currency),
                "price_rental": format_price_minor(row["price_rental_minor"], currency),
                "price_note": row["price_note"],
                "session_label": row["session_label"],
                "age_note": row["age_note"],
            }
        )
    return [arenas[aid] for aid in order]


async def get_city_ice_day(
    session: AsyncSession, *, city_id: int, on_date: date | None = None
) -> dict[str, Any]:
    """
    Массовые катания города на день. Если на сегодня всё уже прошло — отдаём завтра.

    Возврат пустого дня — нормальный, а не ошибочный результат: страница обязана честно
    сказать «на сегодня сеансов нет», а не притворяться, что данные ещё грузятся.
    Поле ``is_today`` говорит, какой день в итоге показан, чтобы заголовок не врал.
    """
    tz_name = await _city_timezone(session, city_id)
    today = _local_today(tz_name)
    now = datetime.now(timezone.utc)

    day = on_date or today
    rows = await _load_day(session, city_id=city_id, day=day, now=now)
    fell_through = False
    if not rows and on_date is None:
        day = today + timedelta(days=1)
        rows = await _load_day(session, city_id=city_id, day=day, now=now)
        fell_through = True

    arenas = _group_by_arena(rows)
    sessions_total = sum(len(a["sessions"]) for a in arenas)
    prices = [
        int(s["price_adult_minor"])
        for a in arenas
        for s in a["sessions"]
        if s["price_adult_minor"] is not None
    ]
    currency = next(
        (s["currency_code"] for a in arenas for s in a["sessions"] if s["currency_code"]),
        "BYN",
    )
    return {
        "city_id": int(city_id),
        "timezone": tz_name,
        "local_date": day.isoformat(),
        "is_today": day == today and not fell_through,
        "day_label": human_date(day, today=today),
        "arenas": arenas,
        "arena_count": len(arenas),
        "session_count": sessions_total,
        "price_min_minor": min(prices) if prices else None,
        "price_max_minor": max(prices) if prices else None,
        "currency_code": currency,
    }


def price_range_line(day: Mapping[str, Any]) -> str:
    """``"от 8 до 12 BYN"`` / ``"8 BYN"`` / ``""`` — если цен нет вовсе, врать нечем."""
    lo, hi = day.get("price_min_minor"), day.get("price_max_minor")
    currency = day.get("currency_code") or "BYN"
    if lo is None or hi is None:
        return ""
    if lo == hi:
        return format_price_minor(lo, currency)
    return f"от {format_price_minor(lo, currency)} до {format_price_minor(hi, currency)}"


def price_range_compact(day: Mapping[str, Any]) -> str:
    """
    ``"8–15 BYN"`` вместо ``"от 8 BYN до 15 BYN"`` — форма для OG-картинки.

    На карточке 1200×630 «от … до …» набирается крупным кеглем и не влезает в колонку:
    обрезанная цена («от 8 BYN д…») хуже, чем её отсутствие. В тексте сообщения
    остаётся развёрнутая формулировка — там места достаточно.
    """
    lo, hi = day.get("price_min_minor"), day.get("price_max_minor")
    currency = day.get("currency_code") or "BYN"
    if lo is None or hi is None:
        return ""
    if lo == hi:
        return format_price_minor(lo, currency)
    low_only = format_price_minor(lo, currency).replace(f" {currency}", "")
    return f"{low_only}–{format_price_minor(hi, currency)}"


def summary_line(day: Mapping[str, Any], *, city_name: str) -> str:
    """Одна строка для og:description и для тела шеринга. Только факты из выборки."""
    arenas = int(day.get("arena_count") or 0)
    sessions = int(day.get("session_count") or 0)
    label = str(day.get("day_label") or "сегодня")
    if not sessions:
        return f"{city_name}: на {label} массовых катаний в расписании нет."
    a_word = plural_ru(arenas, "катке", "катках", "катках")
    s_word = plural_ru(sessions, "сеанс", "сеанса", "сеансов")
    line = f"{city_name}, {label}: {sessions} {s_word} на {arenas} {a_word}"
    prices = price_range_line(day)
    if prices:
        line += f", {prices}"
    return line + "."


SHARE_OPENER = "Расписание массовых катаний — всё в одном месте 👇"


def compose_ice_city_day_share_message(
    *, city_name: str, day: Mapping[str, Any], page_url: str
) -> str:
    """
    Полное тело для Telegram share: ссылка первой строкой, затем opener и сводка.

    Форма намеренно повторяет ``compose_client_share_message`` — тот же контракт
    ``share_url``/``share_body``/``share_text``, поэтому фронт переиспользует
    ``openTelegramShareUrlFromMiniApp`` без правок.
    """
    url = (page_url or "").strip()
    lines = [url, "", SHARE_OPENER, "", summary_line(day, city_name=city_name)]
    return "\n".join(lines)


def ice_city_day_page_url(*, base_url: str, city_name: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    return f"{base}/ice/{city_slug(city_name)}/today"
