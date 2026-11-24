"""TASK-449 (этап 4): расписание «Льда» v2 — GET /api/webapp/client/ice/schedule.

Один запрос на неделю (сегодня..+6) по городу, все три вида; дальше чистый Python
(``shape_schedule``) — заголовок-ответ, «идёт сейчас», группы по дням, «завтра с утра»,
«следующий лёд». Договор — макет 14 (``/tmp/glide-doc/mock-13.jpeg``).
"""

from __future__ import annotations

import json
import time as _time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import (
    DEFAULT_TIMEZONE,
    ICE_CITY_DAY_FROM_SQL,
    _city_timezone,
    _hhmm,
    _local_today,
    format_price_minor,
    plural_ru,
    resolve_city_by_ref,
)
from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.application.style_b import b_photo_url
from src.shared.arena_schedule_mode import arena_schedule_mode_sql
from src.shared.city_locative import city_locative
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.public_display import format_public_name

# Виды на плитках. Массовое = public_skate + open_ice + family_skate.
KIND_GROUPS: dict[str, tuple[str, ...]] = {
    "skate": ("public_skate", "open_ice", "family_skate"),
    "ohm": ("hockey_practice",),
    "figure": ("figure_free",),
}
KIND_TILE_LABEL = {"skate": "Массовое", "ohm": "С клюшкой", "figure": "Фигурное"}
# Родительный для заголовка «16 сеансов массового».
KIND_TITLE_WORD = {"skate": "массового", "ohm": "с клюшкой", "figure": "фигурного"}
ALL_KINDS = tuple(k for kinds in KIND_GROUPS.values() for k in kinds)

WINDOW_DAYS = 7
ONGOING_DROP_MIN = 15
NIGHT_MIN = 180  # «ближайший через N ч» — ночной вариант подзаголовка  # «идёт» уходит из группы, когда до конца < 15 минут
MORNING_END = "12:00"  # «Завтра с утра» — сеансы до полудня
CACHE_TTL_SEC = 60

_WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_WEEKDAYS_ALL = ("Весь понедельник", "Весь вторник", "Всю среду", "Весь четверг", "Всю пятницу", "Всю субботу", "Всё воскресенье")
_MONTHS_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

_schedule_cache: dict[tuple[int, str, str], tuple[float, dict[str, Any]]] = {}


def invalidate_ice_schedule_cache() -> None:
    _schedule_cache.clear()


# ── загрузка ─────────────────────────────────────────────────────────────────

_WEEK_SQL = text(
    f"""
SELECT
    a.id            AS arena_id,
    a.name          AS arena_name,
    p.slug          AS arena_slug,
    s.id            AS session_id,
    s.kind          AS kind,
    s.starts_at_utc,
    s.ends_at_utc,
    s.starts_at_local,
    s.ends_at_local,
    s.local_date,
    s.price_adult_minor,
    s.price_rental_minor,
    s.currency_code
{ICE_CITY_DAY_FROM_SQL}
WHERE a.city_id = :cid
  AND s.local_date >= :d_from AND s.local_date <= :d_to
  AND {PUBLIC_ARENA_VISIBLE_SQL}
  AND {arena_schedule_mode_sql()} <> 'season_closed'
  AND s.status = :st
  AND s.kind = ANY(:kinds)
  AND s.ends_at_utc > :now
  AND (s.valid_until IS NULL OR s.valid_until >= :now)
ORDER BY s.local_date, s.starts_at_local, a.name, s.id
"""
)

# Фото катков города — та же media-выборка, что у хаба, но только id/name/slug/variants.
_ARENAS_SQL = text(
    f"""
    SELECT a.id, a.name, a.address, p.slug,
           (
               SELECT m.variants
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS photo_variants
    FROM arenas a
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE a.city_id = :city_id AND {PUBLIC_ARENA_VISIBLE_SQL}
      AND COALESCE(a.venue_type, 'ice') IN ('ice', 'rink', 'stadium', 'outdoor')
    ORDER BY a.name, a.id
    """
)


async def _load_week(
    session: AsyncSession, *, city_id: int, d_from: date, d_to: date, now: datetime
) -> list[Mapping[str, Any]]:
    rows = (
        await session.execute(
            _WEEK_SQL,
            {
                "cid": int(city_id),
                "d_from": d_from,
                "d_to": d_to,
                "now": now,
                "st": STATUS_ACTIVE,
                "kinds": list(ALL_KINDS),
                **public_scope_params(),
            },
        )
    ).mappings().all()
    return list(rows)


async def _load_arenas(session: AsyncSession, *, city_id: int) -> list[dict[str, Any]]:
    rows = (await session.execute(_ARENAS_SQL, {"city_id": int(city_id), **public_scope_params()})).mappings().all()
    out = []
    for row in rows:
        raw = row.get("photo_variants")
        if isinstance(raw, str):
            raw = json.loads(raw)
        variants = raw if isinstance(raw, Mapping) else {}
        out.append(
            {
                "id": int(row["id"]),
                "name": format_public_name(str(row["name"])),
                "address": str(row.get("address") or ""),
                "slug": str(row.get("slug") or ""),
                "photo": {
                    "thumb": b_photo_url(variants.get("thumb") or variants.get("card")),
                    "card": b_photo_url(variants.get("card") or variants.get("thumb")),
                },
            }
        )
    return out


# ── чистый шейпинг ───────────────────────────────────────────────────────────


def _kind_group(kind: str) -> str | None:
    for key, kinds in KIND_GROUPS.items():
        if kind in kinds:
            return key
    return None


def _day_label(d: date) -> str:
    return f"{_WEEKDAYS_SHORT[d.weekday()]}, {d.day}"


def _day_label_long(d: date) -> str:
    return f"{_WEEKDAYS_SHORT[d.weekday()]}, {d.day} {_MONTHS_GEN[d.month - 1]}"


def weekend_days(today: date) -> list[date]:
    """Ближайшие выходные: если сегодня сб/вс — текущие, иначе следующие."""
    shift = (5 - today.weekday()) % 7
    sat = today + timedelta(days=shift)
    return [sat, sat + timedelta(days=1)]


def resolve_day(day: str, today: date) -> list[date] | None:
    """Даты выбранной вкладки. ``None`` — неизвестный ключ (роут отвечает 422)."""
    day = (day or "today").strip().lower()
    if day == "today":
        return [today]
    if day == "tomorrow":
        return [today + timedelta(days=1)]
    if day == "weekend":
        return weekend_days(today)
    if day == "week":
        return [today + timedelta(i) for i in range(WINDOW_DAYS)]
    try:
        return [date.fromisoformat(day)]
    except ValueError:
        return None


def _price_line(row: Mapping[str, Any]) -> str:
    currency = row.get("currency_code") or "BYN"
    parts = []
    end = _hhmm(row.get("ends_at_local"))
    if end:
        parts.append(f"до {end}")
    adult = format_price_minor(row.get("price_adult_minor"), currency)
    if adult:
        parts.append(adult)
    rental = format_price_minor(row.get("price_rental_minor"), currency)
    if rental:
        # «прокат 8», без повторной валюты — как на макете.
        short = rental.rsplit(" ", 1)[0]
        parts.append(f"прокат {short}")
    return " · ".join(parts)


def _row(row: Mapping[str, Any], photo: Mapping[str, Any], *, now_local: datetime) -> dict[str, Any]:
    ends = row.get("ends_at_utc")
    minutes_left = None
    if isinstance(ends, datetime):
        end_aware = ends if ends.tzinfo else ends.replace(tzinfo=timezone.utc)
        minutes_left = max(0, int((end_aware - now_local).total_seconds() // 60))
    group = _kind_group(str(row.get("kind") or "")) or "skate"
    return {
        "session_id": int(row["session_id"]),
        "arena_id": int(row["arena_id"]),
        "arena_name": format_public_name(str(row.get("arena_name") or "")),
        "photo": {"thumb": photo.get("thumb"), "card": photo.get("card")},
        "time": _hhmm(row.get("starts_at_local")),
        "end": _hhmm(row.get("ends_at_local")),
        "minutes_left": minutes_left,
        "price_line": _price_line(row),
        "kind": group,
        "href": f"arena?ref={int(row['arena_id'])}&s={int(row['session_id'])}",
    }


def _sessions_count_title(n: int, kind: str) -> str:
    return f"{n} {plural_ru(n, 'сеанс', 'сеанса', 'сеансов')} {KIND_TITLE_WORD.get(kind, '')}".strip()


def _human_delta(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} мин"
    h, m = divmod(minutes, 60)
    return f"{h} ч {m} мин" if m else f"{h} ч"


def shape_schedule(
    rows: Sequence[Mapping[str, Any]],
    arenas: Sequence[Mapping[str, Any]],
    *,
    city: Mapping[str, Any],
    day: str,
    kind: str,
    now: datetime,
    today: date,
    tz_name: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """Чистая сборка ответа: на вход — строки недели и катки города."""
    tz = ZoneInfo(tz_name)
    now_local = now.astimezone(tz)
    now_hhmm = f"{now_local.hour:02d}:{now_local.minute:02d}"
    window = {today + timedelta(i) for i in range(WINDOW_DAYS)}

    kind = kind if kind in KIND_GROUPS else "skate"
    day = (day or "today").strip().lower()
    sel_dates = resolve_day(day, today) or [today]
    sel_set = set(sel_dates)

    photos = {int(a["id"]): a.get("photo") or {} for a in arenas}
    kind_rows = [r for r in rows if _kind_group(str(r.get("kind") or "")) == kind]

    def by_date(rs: Sequence[Mapping[str, Any]]) -> dict[date, list[Mapping[str, Any]]]:
        out: dict[date, list[Mapping[str, Any]]] = {}
        for r in rs:
            ld = r.get("local_date")
            if isinstance(ld, str):
                ld = date.fromisoformat(ld[:10])
            if isinstance(ld, datetime):
                ld = ld.date()
            if isinstance(ld, date):
                out.setdefault(ld, []).append(r)
        return out

    by_kind_date = by_date(kind_rows)
    by_all_date = by_date(rows)

    wknd = set(weekend_days(today))
    week_n = len(kind_rows)
    days_meta = [
        ("today", "Сегодня", len(by_kind_date.get(today, []))),
        ("tomorrow", "Завтра", len(by_kind_date.get(today + timedelta(days=1), []))),
        ("weekend", "Выходные", sum(len(by_kind_date.get(d, [])) for d in wknd)),
        ("week", "Неделя", week_n),
    ]
    days_out = [{"key": k, "label": lb, "count": n} for k, lb, n in days_meta]

    sel_rows_all = [r for r in rows if _row_date(r) in sel_set]
    kind_week_counts = {k: sum(1 for r in rows if _kind_group(str(r.get("kind") or "")) == k) for k in KIND_GROUPS}
    sel_day_counts = {k: 0 for k in KIND_GROUPS}
    for r in sel_rows_all:
        g = _kind_group(str(r.get("kind") or ""))
        if g:
            sel_day_counts[g] += 1
    kinds_out = [
        {"key": k, "label": KIND_TILE_LABEL[k], "count": sel_day_counts[k], "week_count": kind_week_counts[k]}
        for k in ("skate", "ohm", "figure")
    ]

    sel_rows = [r for r in kind_rows if _row_date(r) in sel_set]
    sel_rows.sort(key=lambda r: (_row_date(r) or today, _hhmm(r.get("starts_at_local"))))

    photos_fallback = {"thumb": None, "card": None}

    def mk(r: Mapping[str, Any]) -> dict[str, Any]:
        return _row(r, photos.get(int(r["arena_id"]), photos_fallback), now_local=now_local)

    out: dict[str, Any] = {
        "city": {
            "id": int(city["id"]),
            "name": format_public_name(str(city["name"])),
            "name_in": city_locative(str(city["name"])),
        },
        "now_local": now_hhmm,
        "kind": kind,
        "day": day,
        "kinds": kinds_out,
        "days": days_out,
        "ongoing": [],
        "now_line": None,
        "upcoming": [],
        "groups": [],
        "tomorrow_morning": None,
        "next_ice": None,
        "one_rink": len(arenas) == 1,
        "rink": None,
        "week": None,
        "arenas": [{"id": int(a["id"]), "name": str(a["name"])} for a in arenas],
    }

    single_day = len(sel_dates) == 1
    if single_day:
        single = sel_dates[0]
        ongoing = []
        upcoming = []
        if single == today:
            for r in sel_rows:
                start_utc = _aware(r.get("starts_at_utc"))
                end_utc = _aware(r.get("ends_at_utc"))
                if start_utc and end_utc and start_utc <= now < end_utc:
                    left = int((end_utc - now).total_seconds() // 60)
                    if left >= ONGOING_DROP_MIN:
                        ongoing.append(mk(r))
                    # < 15 минут до конца — сеанс уходит из списка совсем.
                else:
                    upcoming.append(mk(r))
            ongoing.sort(key=lambda x: x["end"])
        else:
            upcoming = [mk(r) for r in sel_rows]
        out["ongoing"] = ongoing
        out["upcoming"] = upcoming
        if single == today and upcoming:
            out["now_line"] = f"Сейчас {now_hhmm}"
    else:
        grouped: dict[date, list[Mapping[str, Any]]] = {}
        for r in sel_rows:
            ld = _row_date(r)
            if ld is None:
                continue
            if ld == today:
                # Запрос уже отрезал ends_at_utc <= now — идущий сеанс с < 15 мин до конца уходит.
                end_utc = _aware(r.get("ends_at_utc"))
                if end_utc and int((end_utc - now).total_seconds() // 60) < ONGOING_DROP_MIN:
                    continue
            grouped.setdefault(ld, []).append(mk(r))
        out["groups"] = [
            {"date": d.isoformat(), "label": _day_label(d), "rows": grouped[d]}
            for d in sorted(grouped)
        ]

    # «Завтра с утра» — первые утренние сеансы завтрашнего дня с тем же фильтром.
    # Блок живёт в конце списка «Сегодня» (в т.ч. когда лёд на сегодня кончился).
    tomorrow = today + timedelta(days=1)
    tomorrow_rows = by_kind_date.get(tomorrow, [])
    morning = [r for r in tomorrow_rows if _hhmm(r.get("starts_at_local")) < MORNING_END]
    if tomorrow_rows and day == "today":
        out["tomorrow_morning"] = {
            "label": _day_label_long(tomorrow),
            "all_label": _WEEKDAYS_ALL[tomorrow.weekday()],
            "rows": [mk(r) for r in (morning or tomorrow_rows)[:3]],
            "total": len(tomorrow_rows),
            "href_day": "tomorrow",
        }

    tomorrow_n = len(tomorrow_rows)
    if tomorrow_n == 0:
        for d in sorted(d2 for d2 in (set(by_kind_date) & window) if d2 > tomorrow):
            out["next_ice"] = {"label": _day_label(d), "date": d.isoformat()}
            break

    # Один каток в городе: карточка катка + неделя строками-чипсами (дни без сеансов пропускаем).
    if out["one_rink"] and arenas:
        a0 = arenas[0]
        out["rink"] = {
            "id": int(a0["id"]),
            "name": str(a0["name"]),
            "address": str(a0.get("address") or ""),
            "photo": a0.get("photo") or {},
            "href": f"arena?ref={int(a0['id'])}",
        }
        if day == "today":
            week = []
            for i in range(1, WINDOW_DAYS):
                d = today + timedelta(days=i)
                day_rows = sorted(by_kind_date.get(d, []), key=lambda r: _hhmm(r.get("starts_at_local")))
                if not day_rows:
                    continue
                label = "Завтра" if i == 1 else _WEEKDAYS_SHORT[d.weekday()].capitalize()
                week.append({
                    "date": d.isoformat(),
                    "label": label,
                    "sub": str(d.day),
                    "times": [
                        {"time": _hhmm(r.get("starts_at_local")), "session_id": int(r["session_id"]),
                         "href": f"arena?ref={int(r['arena_id'])}&s={int(r['session_id'])}"}
                        for r in day_rows[:6]
                    ],
                })
            out["week"] = week

    # Заголовок-ответ.
    n_sel = len(sel_rows)
    arenas_today = len({int(r["arena_id"]) for r in sel_rows})
    if day == "today":
        if not sel_rows:
            if tomorrow_n:
                first_t = _hhmm(tomorrow_rows[0].get("starts_at_local"))
                sub = f"завтра {tomorrow_n} {plural_ru(tomorrow_n, 'сеанс', 'сеанса', 'сеансов')} · первый в {first_t}"
            elif out["next_ice"]:
                sub = f"ближайший — {out['next_ice']['label']}"
            else:
                sub = "новых расписаний пока нет"
            out["title"] = {"main": "Сегодня лёд закончился", "sub_parts": [{"text": sub}]}
        elif out["ongoing"]:
            all_today = len(by_all_date.get(today, []))
            live_n = len(out["ongoing"])
            rinks_all = len({int(r["arena_id"]) for r in by_all_date.get(today, [])})
            out["title"] = {
                "main": _sessions_count_title(n_sel, kind),
                "sub_parts": [
                    {"text": f"из {all_today} сегодня · на {_rinks_txt(rinks_all)} · "},
                    {"text": f"{live_n} {_live_word(live_n)}", "tone": "live"},
                ],
            }
        else:
            first = sel_rows[0]
            delta_min = 0
            start_utc = _aware(first.get("starts_at_utc"))
            if start_utc:
                delta_min = max(0, int((start_utc - now).total_seconds() // 60))
            rinks_txt = _rinks_txt(arenas_today)
            nearest = f"ближайший в {_hhmm(first.get('starts_at_local'))}, через {_human_delta(delta_min)}"
            if delta_min >= NIGHT_MIN:
                sub_parts = [{"text": f"сегодня на {rinks_txt} · {nearest}"}]
            else:
                all_today = len(by_all_date.get(today, []))
                sub_parts = [
                    {"text": f"из {all_today} сегодня · на {rinks_txt} · "},
                    {"text": nearest, "tone": "live"},
                ] if delta_min < 60 else [{"text": f"из {all_today} сегодня · на {rinks_txt} · {nearest}"}]
            out["title"] = {
                "main": _sessions_count_title(n_sel, kind),
                "sub_parts": sub_parts,
            }
    else:
        scopes = {"tomorrow": "завтра", "weekend": "на выходных", "week": "на неделе"}
        sub_scope = scopes.get(day) or f"{_day_label_long(sel_dates[0])}"
        out["title"] = {
            "main": _sessions_count_title(n_sel, kind),
            "sub_parts": [{"text": f"{sub_scope} · на {_rinks_txt(arenas_today)}"}]
            if n_sel
            else [{"text": "сеансов нет"}],
        }
    return out


def _rinks_txt(n: int) -> str:
    return "одном катке" if n == 1 else f"{n} {plural_ru(n, 'катке', 'катках', 'катках')}"


def _live_word(n: int) -> str:
    return f"{plural_ru(n, 'идёт', 'идут', 'идут')} сейчас"


def _row_date(row: Mapping[str, Any]) -> date | None:
    ld = row.get("local_date")
    if isinstance(ld, datetime):
        return ld.date()
    if isinstance(ld, date):
        return ld
    if isinstance(ld, str):
        try:
            return date.fromisoformat(ld[:10])
        except ValueError:
            return None
    return None


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ── вход точки API ───────────────────────────────────────────────────────────


async def get_ice_schedule(
    session: AsyncSession,
    *,
    city_id: int,
    day: str,
    kind: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Ответ для ``GET /client/ice/schedule``. ``None`` — города нет в витрине (404)."""
    now = _aware(now or datetime.now(timezone.utc)) or datetime.now(timezone.utc)
    city = await resolve_city_by_ref(session, str(int(city_id)))
    if city is None:
        return None

    day_key = (day or "today").strip().lower()
    kind_key = (kind or "skate").strip().lower()
    tz_name = await _city_timezone(session, int(city_id))
    today = _local_today(tz_name, now)
    if resolve_day(day_key, today) is None or kind_key not in KIND_GROUPS:
        return {"__invalid__": True}

    cache_key = (int(city_id), day_key, kind_key)
    hit = _schedule_cache.get(cache_key)
    if hit and hit[0] > _time.monotonic():
        return hit[1]

    # «Выходные» могут упираться за неделю (сегодня вс → вс следующей недели).
    d_to = max(today + timedelta(days=WINDOW_DAYS - 1), weekend_days(today)[-1])
    rows = await _load_week(session, city_id=int(city_id), d_from=today, d_to=d_to, now=now)
    arenas = await _load_arenas(session, city_id=int(city_id))
    payload = shape_schedule(rows, arenas, city=city, day=day_key, kind=kind_key, now=now, today=today, tz_name=tz_name)
    _schedule_cache[cache_key] = (_time.monotonic() + CACHE_TTL_SEC, payload)
    return payload
