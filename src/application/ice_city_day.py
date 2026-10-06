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

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.application.schedule_staleness import (
    LEVEL_STALE,
    LEVEL_VERY_STALE,
    load_arena_freshness,
    stale_note,
    staleness_level,
    very_stale_note,
)
from src.shared.arena_schedule_mode import arena_schedule_mode_sql
from src.shared.ice_discovery_scope import (
    PUBLIC_ARENA_VISIBLE_SQL,
    ice_discovery_countries,
    public_city_scope_sql,
    public_scope_params,
)

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


# Публичных городов десятки, а читают их на каждый /p/ и /c/. Кэш на процесс.
# Сброс — смена города в админке и конец TTL. Между тестами кэш чистит conftest:
# откат транзакции сам строки не забывает.
PUBLIC_CITY_CACHE_TTL_SEC = 120

_public_cities_cache: dict[tuple[str, ...], tuple[float, list[dict[str, Any]]]] = {}


def invalidate_public_city_cache() -> None:
    """Сбросить кэш публичных городов. Зовётся после создания и правки города в админке."""
    _public_cities_cache.clear()


async def _public_cities(session: AsyncSession) -> list[dict[str, Any]]:
    countries = ice_discovery_countries()
    now = time.monotonic()
    hit = _public_cities_cache.get(countries)
    if hit is not None and hit[0] > now:
        return hit[1]
    result = await session.execute(
        text(
            f"SELECT id, name, country FROM cities WHERE {public_city_scope_sql('cities')} "
            "ORDER BY sort_order, id"
        ),
        public_scope_params(),
    )
    rows = [dict(row) for row in result.mappings().all()]
    _public_cities_cache[countries] = (now + PUBLIC_CITY_CACHE_TTL_SEC, rows)
    return rows


async def resolve_city_by_ref(session: AsyncSession, city_ref: str) -> dict[str, Any] | None:
    """Город по slug (``minsk``) или по числовому id. ``None`` — если такого города нет.

    Только публичные города (TASK-177): активный и в странах витрины. Город вне витрины
    (RU при ``ICE_DISCOVERY_COUNTRIES=BY``) для ``/c/``, ``/ice/…`` и ``/p/`` не существует — 404.
    Список городов берётся из памяти, пока не истечёт TTL и город не изменят в админке.
    """
    ref = (city_ref or "").strip()
    if not ref:
        return None
    rows = await _public_cities(session)
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


def _local_today(tz_name: str, now: datetime | None = None) -> date:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — битый пояс в профиле не должен ронять публичную страницу
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    return (now or datetime.now(timezone.utc)).astimezone(tz).date()


_DAY_SQL = f"""
SELECT
    a.id            AS arena_id,
    a.name          AS arena_name,
    a.address       AS address,
    p.slug          AS arena_slug,
    p.district      AS district,
    p.phone         AS phone,
    p.website_url   AS website_url,
    p.tickets_url   AS tickets_url,
    s.id            AS session_id,
    s.kind          AS kind,
    s.starts_at_utc,
    s.ends_at_utc,
    s.starts_at_local,
    s.ends_at_local,
    s.price_adult_minor,
    s.price_child_minor,
    s.price_rental_minor,
    s.currency_code,
    s.price_note,
    s.session_label,
    s.age_note,
    s.schedule_basis
FROM ice_sessions s
JOIN arenas a ON a.id = s.arena_id
LEFT JOIN arena_profiles p ON p.arena_id = a.id
JOIN cities c ON c.id = a.city_id
WHERE a.city_id = :cid
  AND {PUBLIC_ARENA_VISIBLE_SQL}
  AND {arena_schedule_mode_sql()} <> 'season_closed'
  AND s.status = :st
  AND s.kind IN ('public_skate', 'open_ice')
  AND s.local_date = :day
  AND s.starts_at_utc > :now
  AND (s.valid_until IS NULL OR s.valid_until >= :now)
ORDER BY a.name, s.starts_at_local, s.id
"""


def _iso_utc(value: Any) -> str | None:
    """ISO-8601 для JSON-LD ``startDate``/``endDate``. Наивный штамп считаем UTC."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


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
            **public_scope_params(),
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
                "starts_at_utc": _iso_utc(row["starts_at_utc"]),
                "ends_at_utc": _iso_utc(row["ends_at_utc"]),
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
                "schedule_basis": row.get("schedule_basis") or "live",
            }
        )
    return [arenas[aid] for aid in order]


async def _load_day_checked(
    session: AsyncSession, *, city_id: int, day: date, now: datetime
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Сеансы дня, разделённые по свежести расписания арены (TASK-180).

    Арена, чей парсер не читал сайт успешно дольше 72 ч, в список дня не попадает:
    её сеансы больше не выдаём за расписание, она уходит в «Расписание не подтверждено».
    """
    rows = await _load_day(session, city_id=city_id, day=day, now=now)
    fresh = await load_arena_freshness(session, {int(r["arena_id"]) for r in rows}, now=now)
    shown: list[Mapping[str, Any]] = []
    unconfirmed: dict[int, dict[str, Any]] = {}
    for row in rows:
        aid = int(row["arena_id"])
        level = staleness_level(fresh.get(aid))
        if level != LEVEL_VERY_STALE:
            shown.append(row)
            continue
        if aid not in unconfirmed:
            phone = str(row["phone"] or "").strip()
            site = str(row["tickets_url"] or row["website_url"] or "").strip()
            unconfirmed[aid] = {
                "arena_id": aid,
                "name": row["arena_name"],
                "slug": row["arena_slug"],
                "phone": phone or None,
                "note": very_stale_note(
                    fresh.get(aid), now=now, has_phone=bool(phone), has_site=bool(site)
                ),
            }
    return shown, list(unconfirmed.values()), fresh


async def get_city_ice_day(
    session: AsyncSession,
    *,
    city_id: int,
    on_date: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Массовые катания города на день. Если на сегодня всё уже прошло — отдаём завтра.

    Возврат пустого дня — нормальный, а не ошибочный результат: страница обязана честно
    сказать «на сегодня сеансов нет», а не притворяться, что данные ещё грузятся.
    Поле ``is_today`` говорит, какой день в итоге показан, чтобы заголовок не врал.

    TASK-180: у арены с устаревшим расписанием (> 6 ч) — ``stale_note``; арены
    без удачного прогона > 72 ч исключены из дня и перечислены в ``unconfirmed``.
    """
    tz_name = await _city_timezone(session, city_id)
    now = now or datetime.now(timezone.utc)
    today = _local_today(tz_name, now)

    day = on_date or today
    rows, unconfirmed, fresh = await _load_day_checked(session, city_id=city_id, day=day, now=now)
    fell_through = False
    # TASK-180: если сегодня сеансы есть, но все — у арен с неподтверждённым расписанием,
    # день остаётся сегодняшним: список «Расписание не подтверждено» и есть ответ на сегодня.
    if not rows and not unconfirmed and on_date is None:
        day = today + timedelta(days=1)
        rows, unconfirmed, fresh = await _load_day_checked(
            session, city_id=city_id, day=day, now=now
        )
        fell_through = True

    arenas = _group_by_arena(rows)
    for arena in arenas:
        arena_fresh = fresh.get(int(arena["arena_id"]))
        arena["stale"] = staleness_level(arena_fresh) == LEVEL_STALE
        arena["stale_note"] = stale_note(arena_fresh, now=now)
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
        "stale_arena_count": sum(1 for a in arenas if a["stale"]),
        "unconfirmed": unconfirmed,
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


def cacheable_day_label(day: Mapping[str, Any]) -> str:
    """«Пт, 3 окт» из ``local_date``. Для og, картинки и текста в чате — не «сегодня»."""
    raw = day.get("local_date")
    parsed: date | None = raw if isinstance(raw, date) else None
    if parsed is None and isinstance(raw, str) and len(raw) >= 10:
        try:
            parsed = date.fromisoformat(raw[:10])
        except ValueError:
            parsed = None
    if parsed is None:
        return str(day.get("day_label") or "")
    from src.application.place_page import absolute_day_label

    return absolute_day_label(parsed)


def summary_line(day: Mapping[str, Any], *, city_name: str, absolute: bool = False) -> str:
    """Одна строка фактов. ``absolute=True`` — для og и чата, где «сегодня» завтра врёт."""
    arenas = int(day.get("arena_count") or 0)
    sessions = int(day.get("session_count") or 0)
    label = cacheable_day_label(day) if absolute else str(day.get("day_label") or "сегодня")
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
    lines = [url, "", SHARE_OPENER, "", summary_line(day, city_name=city_name, absolute=True)]
    return "\n".join(lines)


def ice_city_day_page_url(*, base_url: str, city_name: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    return f"{base}/ice/{city_slug(city_name)}/today"
