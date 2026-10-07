"""Публичная главная каталога Glide — ``/`` (TASK-191-A, TASK-210-A)."""

from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import (
    ICE_CITY_DAY_FROM_SQL,
    ICE_CITY_DAY_SESSION_WHERE_SQL,
    DEFAULT_TIMEZONE,
    city_slug,
    count_sessions_on_local_calendar_day_by_city,
    human_date,
    plural_ru,
)
from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.application.place_links import join_public_origin, place_path
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.copy_ru import t

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "catalog-home.html"
_NATIONWIDE_SESSIONS = 3  # TASK-210: до 3 ближайших сеансов

# TASK-210: справочник «город → область» для всех публичных BY-городов
_BY_REGIONS: dict[str, str] = {
    "minsk": "Минская область",
    "brest": "Брестская область",
    "gomel": "Гомельская область",
    "grodno": "Гродненская область",
    "mogilev": "Могилёвская область",
    "vitebsk": "Витебская область",
    "baranovichi": "Брестская область",
    "bobruisk": "Могилёвская область",
    "borisov": "Минская область",
    "zhodino": "Минская область",
    "lida": "Гродненская область",
    "mozyr": "Гомельская область",
    "novopolock": "Витебская область",
    "orsha": "Витебская область",
    "pinsk": "Брестская область",
    "polotsk": "Витебская область",
    "rechitsa": "Гомельская область",
    "svetlogorsk": "Гомельская область",
    "slutsk": "Минская область",
    "soligorsk": "Минская область",
    # Добавляем остальные BY города
}

_PLACE_COUNT_SQL = text(
    f"""
    SELECT c.id, c.name, c.country, c.sort_order, COUNT(DISTINCT a.id) AS place_count
    FROM cities c
    JOIN arenas a ON a.city_id = c.id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    WHERE c.id = ANY(:city_ids)
      AND {PUBLIC_ARENA_VISIBLE_SQL}
    GROUP BY c.id, c.name, c.country, c.sort_order
    HAVING COUNT(DISTINCT a.id) > 0
    """
)

_COUNTRY_SECTION_ORDER = ("BY", "RU")
_COUNTRY_SECTION_LABEL = {"BY": "Беларусь", "RU": "Россия"}
_MINSK_SLUG = "minsk"


# TASK-210: выбор периода времени
def _default_when_key(now: datetime) -> str:
    """Умный дефолт: Пн-Пт до 15:00 — 'today'; Пт с 15:00, Сб, Вс — 'weekend'."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)  # Europe/Minsk
    local = now.astimezone(tz)
    weekday = local.weekday()  # 0 = Пн, 4 = Пт, 5 = Сб, 6 = Вс

    # Пт с 15:00 до конца дня — weekend
    if weekday == 4 and local.time() >= time(15, 0):
        return "weekend"
    # Сб весь день — weekend
    if weekday == 5:
        return "weekend"
    # Вс до 18:00 — weekend; после 18:00 — следующие выходные
    if weekday == 6:
        if local.time() < time(18, 0):
            return "weekend"
        else:
            return "weekend"  # следующие выходные, но всё равно ключ weekend
    # Остальное — today
    return "today"


def _parse_when(when: str | None, now: datetime) -> tuple[str, datetime, datetime]:
    """Возвращает (key, starts_at, ends_at) для фильтрации сеансов."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    local = now.astimezone(tz)
    today = local.date()

    key = (when or "").strip().lower()
    if not key or key not in ("today", "tomorrow", "weekend", "day"):
        key = _default_when_key(now)

    # Сегодня: с now до конца дня
    if key == "today":
        starts_at = now
        ends_at = datetime.combine(today + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        return "today", starts_at, ends_at

    # Завтра: завтра весь день
    if key == "tomorrow":
        tomorrow = today + timedelta(days=1)
        starts_at = datetime.combine(tomorrow, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        ends_at = datetime.combine(tomorrow + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        return "tomorrow", starts_at, ends_at

    # В выходные: Сб 00:00 - Пн 00:00 (или с текущего момента, если сейчас выходные)
    if key == "weekend":
        # Если сейчас Сб или Вс, начинаем с текущего момента
        if today.weekday() in (5, 6):  # Сб или Вс
            saturday = today - timedelta(days=today.weekday() - 5)
        else:
            # Ближайшая суббота
            saturday = today + timedelta(days=(5 - today.weekday()) % 7)
            if saturday == today and local.time() >= time(18, 0) and today.weekday() == 6:
                # Вс после 18:00 — следующие выходные
                saturday = today + timedelta(days=6)

        monday = saturday + timedelta(days=2)
        starts_at = max(now, datetime.combine(saturday, time(0, 0), tzinfo=tz).astimezone(timezone.utc))
        ends_at = datetime.combine(monday, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        return "weekend", starts_at, ends_at

    # day — обрабатывается отдельно через ?d=
    return key, now, now


def _parse_day_date(d: str | None, now: datetime) -> date | None:
    """Парсит ?d=YYYY-MM-DD, возвращает дату или None."""
    if not d:
        return None
    try:
        parsed = date.fromisoformat(d.strip())
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        today = now.astimezone(tz).date()
        # Проверяем, что дата в допустимом диапазоне (сегодня ... +7 дней)
        if today <= parsed <= today + timedelta(days=7):
            return parsed
    except (ValueError, AttributeError):
        pass
    return None


def _is_minsk_city(city: Mapping[str, Any]) -> bool:
    return str(city.get("slug") or "") == _MINSK_SLUG or str(city.get("name") or "").strip() == "Минск"


def _city_rank_key(city: Mapping[str, Any]) -> tuple[Any, ...]:
    """Минск первым в секции страны, далее по активности (сеансы сегодня, места, имя)."""
    return (
        0 if _is_minsk_city(city) else 1,
        -int(city.get("session_count") or 0),
        -int(city.get("place_count") or 0),
        str(city.get("name") or ""),
    )


def group_catalog_cities_by_country(cities: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for city in cities:
        code = str(city.get("country") or "BY").strip().upper() or "BY"
        buckets.setdefault(code, []).append(city)
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for code in _COUNTRY_SECTION_ORDER:
        if code in buckets:
            groups.append((code, sorted(buckets.pop(code), key=_city_rank_key)))
    for code in sorted(buckets):
        groups.append((code, sorted(buckets[code], key=_city_rank_key)))
    return groups


def catalog_home_headline(countries: set[str]) -> tuple[str, str]:
    """``(h1, document title)`` — не обещаем «только Беларусь», если в списке есть RU."""
    codes = {c.strip().upper() for c in countries if c}
    if codes == {"BY"} or (not codes):
        h1 = "Катки Беларуси"
        title = "Катки Беларуси — расписание и города | Glide"
    elif codes <= {"BY", "RU"} and "RU" in codes:
        h1 = "Катки — расписание по городам"
        title = "Катки Беларуси и России — расписание и города | Glide"
    else:
        h1 = "Катки — расписание по городам"
        title = "Катки — расписание и города | Glide"
    return h1, title


_UPCOMING_SQL = text(
    f"""
WITH city_clock AS (
    SELECT DISTINCT ON (a.city_id)
           a.city_id,
           COALESCE(p.timezone, '{DEFAULT_TIMEZONE}') AS tz
    FROM arenas a
    JOIN cities c ON c.id = a.city_id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    WHERE c.country = ANY(:ice_countries)
    ORDER BY a.city_id, a.id
)
SELECT c.name AS city_name,
       a.name AS arena_name,
       p.slug AS arena_slug,
       s.id AS session_id,
       s.starts_at_local,
       s.ends_at_local,
       s.local_date,
       s.schedule_basis,
       cc.tz AS city_timezone
{ICE_CITY_DAY_FROM_SQL}
JOIN city_clock cc ON cc.city_id = a.city_id
WHERE {PUBLIC_ARENA_VISIBLE_SQL}
  {ICE_CITY_DAY_SESSION_WHERE_SQL}
ORDER BY s.starts_at_utc, s.id
LIMIT :lim
"""
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value or ""), quote=True)


def _local_today(tz_name: str, now: datetime) -> date:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    return now.astimezone(tz).date()


def _sessions_block_title(sessions: list[Mapping[str, Any]], *, now: datetime) -> str:
    if not sessions:
        return "Лёд сегодня"
    all_today = True
    for row in sessions:
        tz_name = str(row.get("city_timezone") or DEFAULT_TIMEZONE)
        local_date = row.get("local_date")
        if not isinstance(local_date, date):
            continue
        if local_date != _local_today(tz_name, now):
            all_today = False
            break
    return "Лёд сегодня" if all_today else "Ближайший лёд"


_WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MONTHS_SHORT = (
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)


def _session_day_label(row: Mapping[str, Any], *, now: datetime) -> str:
    tz_name = str(row.get("city_timezone") or DEFAULT_TIMEZONE)
    local_date = row.get("local_date")
    if not isinstance(local_date, date):
        return ""
    today = _local_today(tz_name, now)
    relative = human_date(local_date, today=today)
    if relative in ("сегодня", "завтра"):
        return relative
    wd = _WEEKDAYS_SHORT[local_date.weekday()]
    return f"{wd}, {local_date.day} {_MONTHS_SHORT[local_date.month - 1]}"


async def _count_sessions_in_window(
    session: AsyncSession,
    *,
    city_ids: list[int],
    starts_at: datetime,
    ends_at: datetime,
    country: str | None = None,
) -> dict[int, int]:
    """Подсчёт сеансов по городам в заданном временном окне."""
    if not city_ids:
        return {}

    params = {
        "city_ids": city_ids,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "st": STATUS_ACTIVE,
        **public_scope_params(),
    }

    country_filter = ""
    if country:
        params["country"] = country
        country_filter = "AND c.country = :country"

    sql = text(f"""
        SELECT a.city_id, COUNT(DISTINCT s.id) AS session_count
        {ICE_CITY_DAY_FROM_SQL}
        WHERE a.city_id = ANY(:city_ids)
          {country_filter}
          AND {PUBLIC_ARENA_VISIBLE_SQL}
          AND s.status = :st
          AND s.kind IN ('public_skate', 'open_ice')
          AND s.starts_at_utc >= :starts_at
          AND s.starts_at_utc < :ends_at
          AND (s.valid_until IS NULL OR s.valid_until >= :starts_at)
        GROUP BY a.city_id
    """)

    rows = (await session.execute(sql, params)).mappings().all()
    return {int(r["city_id"]): int(r["session_count"]) for r in rows}


async def load_catalog_home_view(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    when: str | None = None,
    day_date: str | None = None,
    user_city_slug: str | None = None,
) -> dict[str, Any]:
    """
    TASK-210-A: загрузка данных главной с выбором периода.

    :param when: 'today'|'tomorrow'|'weekend'|'day' или None (умный дефолт)
    :param day_date: 'YYYY-MM-DD' для when='day'
    :param user_city_slug: slug города из cookie glide_city
    """
    from src.application.ice_city_day import _public_cities

    now = now or _utc_now()

    # Определяем период
    when_key, period_start, period_end = _parse_when(when, now)

    # Если when=day и есть ?d=, обрабатываем конкретную дату
    if when_key == "day":
        target_date = _parse_day_date(day_date, now)
        if target_date:
            tz = ZoneInfo(DEFAULT_TIMEZONE)
            period_start = datetime.combine(target_date, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
            period_end = datetime.combine(target_date + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(
                timezone.utc
            )

    cities = await _public_cities(session)
    if not cities:
        return {
            "cities": [],
            "city_groups": [],
            "sessions": [],
            "sessions_title": t("when.today"),
            "country": "BY",
            "now": now,
            "when_key": when_key,
            "period_start": period_start,
            "period_end": period_end,
        }

    city_ids = [int(c["id"]) for c in cities]

    # Подсчёт мест по городам (не зависит от периода)
    place_rows = (
        (
            await session.execute(
                _PLACE_COUNT_SQL,
                {"city_ids": city_ids, **public_scope_params()},
            )
        )
        .mappings()
        .all()
    )

    # Подсчёт сеансов за выбранный период (только BY для счётчика на главной)
    session_totals = await _count_sessions_in_window(
        session,
        city_ids=city_ids,
        starts_at=period_start,
        ends_at=period_end,
        country="BY",
    )

    catalog_cities: list[dict[str, Any]] = []
    for row in place_rows:
        cid = int(row["id"])
        catalog_cities.append(
            {
                "id": cid,
                "name": str(row["name"]),
                "country": str(row["country"] or ""),
                "slug": city_slug(str(row["name"])),
                "place_count": int(row["place_count"] or 0),
                "session_count": int(session_totals.get(cid, 0)),
            }
        )

    city_groups = group_catalog_cities_by_country(catalog_cities)
    catalog_cities = [city for _, group in city_groups for city in group]

    # Ближайшие сеансы (только своя страна)
    user_city_id = None
    if user_city_slug:
        for city in cities:
            if city_slug(str(city["name"])) == user_city_slug.lower():
                user_city_id = int(city["id"])
                break

    # Если не нашли город из cookie или его нет, берём Минск или первый BY город
    if not user_city_id:
        for city in cities:
            if city_slug(str(city["name"])) == _MINSK_SLUG:
                user_city_id = int(city["id"])
                break
        if not user_city_id:
            # Первый BY город
            for city in cities:
                if str(city.get("country")) == "BY":
                    user_city_id = int(city["id"])
                    break

    upcoming = (
        (
            await session.execute(
                _UPCOMING_SQL,
                {
                    "now": period_start,
                    "st": STATUS_ACTIVE,
                    "lim": _NATIONWIDE_SESSIONS,
                    **public_scope_params(),
                },
            )
        )
        .mappings()
        .all()
    )
    sessions = [dict(r) for r in upcoming]
    sessions_title = _sessions_block_title(sessions, now=now)
    countries = {str(c.get("country") or "") for c in catalog_cities}
    country = "BY" if "BY" in countries else (next(iter(countries), "BY") if countries else "BY")

    return {
        "cities": catalog_cities,
        "city_groups": city_groups,
        "sessions": sessions,
        "sessions_title": sessions_title,
        "country": country,
        "now": now,
        "when_key": when_key,
        "period_start": period_start,
        "period_end": period_end,
        "user_city_id": user_city_id,
        "user_city_slug": user_city_slug or _MINSK_SLUG,
    }


def _city_row(city: Mapping[str, Any]) -> str:
    name = str(city["name"])
    slug = str(city["slug"])
    places = int(city["place_count"] or 0)
    sessions = int(city["session_count"] or 0)
    p_word = plural_ru(places, "место", "места", "мест")
    if sessions:
        s_word = plural_ru(sessions, "сеанс", "сеанса", "сеансов")
        stats = f"{places} {p_word} · {sessions} {s_word} сегодня"
    else:
        stats = f"{places} {p_word}"
    links = f'<a href="/c/{_esc(slug)}">Все места</a>'
    if sessions > 0:
        links += f' · <a href="/ice/{_esc(slug)}/today">Лёд сегодня</a>'
    return (
        '<li class="city">'
        f'<h2 class="city__name"><a href="/c/{_esc(slug)}">{_esc(name)}</a></h2>'
        f'<p class="city__stats">{_esc(stats)}</p>'
        f'<p class="city__links">{links}</p>'
        "</li>"
    )


def _cities_html(city_groups: list[tuple[str, list[Mapping[str, Any]]]]) -> str:
    if not city_groups:
        return '<p class="muted">Пока нет опубликованных городов.</p>'
    parts: list[str] = []
    for code, group in city_groups:
        label = _COUNTRY_SECTION_LABEL.get(code, code)
        parts.append(
            '<section class="country-group">'
            f'<h3 class="country-group__title">{_esc(label)}</h3>'
            '<ul class="cities">' + "".join(_city_row(c) for c in group) + "</ul></section>"
        )
    return "".join(parts)


def _session_row(row: Mapping[str, Any], *, now: datetime) -> str:
    """Рендеринг строки сеанса. TASK-210: projected сеансы — пунктир и метка 'обычно'."""
    city_name = str(row["city_name"])
    slug = str(row.get("arena_slug") or "").strip()
    arena_name = str(row["arena_name"])
    starts = str(row.get("starts_at_local") or "").strip()
    ends = str(row.get("ends_at_local") or "").strip()
    time_text = f"{starts}–{ends}" if starts and ends else (starts or ends or "—")
    day_label = _session_day_label(row, now=now)

    # TASK-210: projected сеансы с меткой
    schedule_basis = str(row.get("schedule_basis") or "live")
    is_projected = schedule_basis == "projected"

    if slug:
        href = place_path(city_name=city_name, slug=slug)
        if row.get("session_id"):
            href += f"?s={int(row['session_id'])}"
        name_html = f'<a href="{_esc(href)}">{_esc(arena_name)}</a>'
    else:
        name_html = _esc(arena_name)

    day_html = f'<span class="session__day">{_esc(day_label)}</span>' if day_label else ""

    # TASK-210: для projected — пунктир и метка
    session_class = "session"
    if is_projected:
        session_class += " session--projected"

    basis_note = ""
    if is_projected:
        basis_note = f' <span class="session__basis">{_esc(t("basis.projected"))}</span>'

    return (
        f'<li class="{session_class}">'
        f'{day_html}<span class="session__time">{_esc(time_text)}</span>'
        f'<span class="session__place">{name_html}</span>'
        f'<span class="session__city">{_esc(city_name)}</span>'
        f"{basis_note}"
        "</li>"
    )


def _json_ld(view: Mapping[str, Any], *, canonical_url: str) -> str:
    elements = []
    for n, city in enumerate(view.get("cities") or []):
        slug = str(city["slug"])
        elements.append(
            {
                "@type": "ListItem",
                "position": n + 1,
                "name": city.get("name"),
                "url": join_public_origin(canonical_url, f"/c/{slug}"),
            }
        )
    graph = [
        {
            "@type": "WebSite",
            "name": "Glide",
            "url": canonical_url,
            "description": "Катки, расписание массовых катаний и лёд сегодня",
        },
        {
            "@type": "ItemList",
            "name": "Города каталога Glide",
            "itemListElement": elements,
        },
    ]
    return json_for_script({"@context": "https://schema.org", "@graph": graph})


def _format_date_string(now: datetime) -> str:
    """Дата-строка по Минску: 'Пятница, 9 октября'."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    local = now.astimezone(tz)
    weekdays = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
    months_gen = (
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
    weekday = weekdays[local.weekday()]
    return f"{weekday.capitalize()}, {local.day} {months_gen[local.month - 1]}"


def _when_label(key: str) -> str:
    """Подпись для переключателя времени."""
    labels = {
        "today": t("when.today"),
        "tomorrow": t("when.tomorrow"),
        "weekend": t("when.weekend"),
        "day": t("when.day"),
    }
    return labels.get(key, t("when.today"))


def _counter_text(session_count: int, city_count: int, when_key: str) -> str:
    """Текст счётчика: 'Сегодня в Беларуси N сеансов в M городах'."""
    s_word = plural_ru(session_count, "сеанс", "сеанса", "сеансов")
    c_word = plural_ru(city_count, "городе", "городах", "городах")

    when_labels = {
        "today": "Сегодня",
        "tomorrow": "Завтра",
        "weekend": "В эти выходные",
        "day": "В этот день",
    }
    when_text = when_labels.get(when_key, "Сегодня")

    return f"{when_text} в Беларуси {session_count} {s_word} в {city_count} {c_word}"


def render_catalog_home_page(
    view: Mapping[str, Any],
    *,
    canonical_url: str,
    og_image_url: str,
    cta_url: str | None,
    trainers_url: str,
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    cities = list(view.get("cities") or [])
    raw_groups = view.get("city_groups")
    if isinstance(raw_groups, list) and raw_groups:
        city_groups = [(str(a), list(b)) for a, b in raw_groups]
    else:
        city_groups = group_catalog_cities_by_country(cities)
    sessions = list(view.get("sessions") or [])
    now = view.get("now") if isinstance(view.get("now"), datetime) else _utc_now()
    country = str(view.get("country") or "BY")
    sessions_title = str(view.get("sessions_title") or t("when.today"))
    lang, og_locale = html_lang_for_country(country)

    when_key = str(view.get("when_key") or "today")

    country_codes = {str(c.get("country") or "BY").upper() for c in cities}
    # TASK-210: нейтральный заголовок (PDEC-019)
    page_h1 = "Где покататься"
    title = "Где покататься в Беларуси — катки и расписание массовых катаний | Glide"
    description = (
        "Где покататься: города с катками, расписание массовых катаний и ссылки на все места в каталоге Glide."
    )
    cities_html = _cities_html(city_groups)
    if sessions:
        sessions_html = '<ul class="sessions">' + "".join(_session_row(s, now=now) for s in sessions) + "</ul>"
    else:
        sessions_html = '<p class="muted">Ближайших сеансов пока нет — загляните в расписание по городу.</p>'

    # Дата-строка
    date_string = _format_date_string(now)

    # Счётчик сеансов (только BY)
    by_cities = [c for c in cities if c.get("country") == "BY"]
    total_sessions = sum(int(c.get("session_count") or 0) for c in by_cities)
    cities_with_sessions = len([c for c in by_cities if int(c.get("session_count") or 0) > 0])
    counter_text = _counter_text(total_sessions, cities_with_sessions, when_key)

    values = {
        "__LANG__": lang,
        "__OG_LOCALE__": og_locale,
        "__OG_TITLE__": _esc(title),
        "__OG_DESCRIPTION__": _esc(description),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_IMAGE__": _esc(og_image_url),
        "__ROBOTS__": "index, follow",
        "__JSONLD__": _json_ld(view, canonical_url=canonical_url),
        "__CITIES__": cities_html,
        "__SESSIONS_TITLE__": _esc(sessions_title),
        "__SESSIONS__": sessions_html,
        "__TRAINERS_URL__": _esc(trainers_url),
        "__PAGE_H1__": _esc(page_h1),
        "__DATE_STRING__": _esc(date_string),
        "__COUNTER_TEXT__": _esc(counter_text),
        "__WHEN_TODAY__": _esc(t("when.today")),
        "__WHEN_TOMORROW__": _esc(t("when.tomorrow")),
        "__WHEN_WEEKEND__": _esc(t("when.weekend")),
        "__WHEN_DAY__": _esc(t("when.day")),
    }
    html = fill_placeholders(template, values)
    if cta_url:
        html = html.replace("__CTA_URL__", _esc(cta_url))
    else:
        start = html.find('<a class="cta cta--secondary"')
        end = html.find("</a>", start)
        if start != -1 and end != -1:
            html = html[:start] + html[end + 4 :]
    return html


def catalog_home_og_image_url(base_url: str) -> str:
    path = "/logos/02-horizontal-full/glide-horizontal-teal-icon-black-text-on-white.png"
    base = (base_url or "").strip().rstrip("/")
    if base.lower().startswith("https://"):
        return f"{base}{path}"
    return path


def parse_city_session_count_from_home(html: str, city_name: str) -> int | None:
    """Тестовый хелпер: «N сеансов сегодня» в карточке города."""
    block = re.search(
        rf'<h2 class="city__name"><a href="[^"]+">{re.escape(city_name)}</a></h2>\s*'
        r'<p class="city__stats">([^<]+)</p>',
        html,
    )
    if not block:
        return None
    stats = block.group(1)
    match = re.search(r"(\d+)\s+сеанс", stats)
    return int(match.group(1)) if match else 0
