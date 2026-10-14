"""
Страница города ``/c/{город}`` без параметров — маршрутизатор потребностей (TASK-224).

Главная выбирает город; эта страница отвечает на вопрос «что нужно?» одним тапом:
плитка = потребность («Покататься», «С клюшкой», «Заточка», «Магазины»,
«Тренеры»), под плиткой — живая строка и быстрые окна времени («Сегодня 3 · Завтра 24 ·
Сб–Вс 27»). Плитка без данных не показывается. Любой параметр (``?t=``, ``?w=``,
``?kind=``, ``?seg=``, ``?svc=``, ``?page=``) — это уже список (``selection_page``).

Макет: design/prototypes/2026-10-09-city-router-home.html, экран 1.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_profile import has_known_hours, intervals_for_weekday, normalize_hhmm
from src.application.arena_public_use_cases import (
    STATUS_ACTIVE,
    _NOT_HOCKEY_CENTER_SQL,
    _OHM_SESSION_SQL,
    city_hockey_center_count,
)
from src.application.catalog_home_page import _USER_UPCOMING_SQL, _session_card
from src.application.ice_city_day import DEFAULT_TIMEZONE, city_slug, format_price_minor, human_date, plural_ru
from src.application.ice_time_windows import home_default_when_key, resolve_window
from src.application.place_links import (
    catalog_start_param,
    join_public_origin,
    place_path,
    place_start_param,
    public_telegram_cta_url,
)
from src.shared.catalog_sharpening import row_in_sharpening_section
from src.shared.catalog_visibility import CATALOG_LISTED_SQL
from src.shared.city_locative import city_locative
from src.application.style_b import b_photo_url
from src.shared.copy_ru import t
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.application.city_style_b import (
    VARIANT_ONE,
    VARIANT_PHONE,
    choose_city_variant,
    load_nearby,
    city_origin,
    load_week,
    price_sentence,
    week_days,
)
from src.shared.phone_guard import is_valid_public_phone, tel_href
from src.shared.public_display import (
    format_clock,
    format_phone_display,
    format_public_name,
    format_street_address,
)
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.specialist_roles import specialist_role_display
from src.shared.venue_types import VENUE_TYPE_ICE, VENUE_TYPE_OUTDOOR, VENUE_TYPE_SHOP

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "place.html"

_UPCOMING_DAYS = 7
_UPCOMING_LIMIT = 3
_UPCOMING_FETCH = 24
_WINDOW_KEYS = ("today", "tomorrow", "weekend")
_SOON_MINUTES = 60

# Сеансы города по окнам, по аренам и по виду (МК / ОХМ) — один запрос.
# «Все» — все будущие сеансы, как в счёте подборки (city_selection_session_counts): og-описание
# хаба и картинка /c/{город}/og.png должны называть одно число.
_WINDOW_COUNTS_SQL = text(
    f"""
    SELECT s.arena_id,
           (s.kind = 'hockey_practice') AS is_ohm,
           COUNT(*) FILTER (WHERE s.starts_at_utc >= :today_from AND s.starts_at_utc < :today_to)::int AS today_n,
           COUNT(*) FILTER (WHERE s.starts_at_utc >= :tomorrow_from AND s.starts_at_utc < :tomorrow_to)::int AS tomorrow_n,
           COUNT(*) FILTER (WHERE s.starts_at_utc >= :weekend_from AND s.starts_at_utc < :weekend_to)::int AS weekend_n,
           COUNT(*)::int AS all_n
    FROM ice_sessions s
    JOIN arenas a ON a.id = s.arena_id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE a.city_id = :city_id
      AND {PUBLIC_ARENA_VISIBLE_SQL}
      AND {_NOT_HOCKEY_CENTER_SQL}
      AND s.status = :st
      AND s.kind IN ('public_skate', 'open_ice', 'hockey_practice')
      AND s.starts_at_utc > :now
      AND (s.valid_until IS NULL OR s.valid_until >= :now)
    GROUP BY s.arena_id, (s.kind = 'hockey_practice')
    """
)

_NEXT_OHM_SQL = text(
    f"""
    SELECT a.id AS arena_id, a.name AS arena_name, p.slug AS arena_slug,
           s.id AS session_id, s.local_date, s.starts_at_local, s.price_adult_minor, s.currency_code,
           COALESCE(p.timezone, '{DEFAULT_TIMEZONE}') AS tz
    FROM ice_sessions s
    JOIN arenas a ON a.id = s.arena_id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE a.city_id = :city_id
      AND {PUBLIC_ARENA_VISIBLE_SQL}
      AND {_NOT_HOCKEY_CENTER_SQL}
      AND {_OHM_SESSION_SQL}
    ORDER BY s.starts_at_utc, s.id
    LIMIT 1
    """
)

# Все публичные места города: тип, часы, услуги — для плиток «Заточка», «Магазины» и
# списка мест внизу (SEO и «мне нужен конкретный каток»).
_PLACES_SQL = text(
    f"""
    SELECT a.id, a.name, COALESCE(a.venue_type, 'ice') AS venue_type,
           a.latitude, a.longitude,
           a.is_active, a.is_confirmed, a.created_by_trainer_id,
           p.slug, a.address, p.opening_hours, p.amenities, p.phone, p.website_url,
           COALESCE(p.schedule_mode, 'auto') AS schedule_mode,
           p.season_start_month, p.season_end_month, p.status AS profile_status,
           c.country, c.is_active AS city_is_active,
           (
               SELECT m.width
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS photo_width,
           (
               SELECT m.variants
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS photo_variants,
           (
               SELECT COALESCE(m.display_tone, false)
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS display_tone,
           EXISTS (
               SELECT 1 FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
           ) AS has_photo,
           COALESCE(p.timezone, '{DEFAULT_TIMEZONE}') AS tz
    FROM arenas a
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE a.city_id = :city_id AND {PUBLIC_ARENA_VISIBLE_SQL}
    ORDER BY a.name, a.id
    """
)

_TRAINERS_SQL = text(
    f"""
    SELECT p.specialist_role, COUNT(DISTINCT t.id)::int AS n
    FROM trainers t
    JOIN trainer_cities tc ON tc.trainer_id = t.id
    LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
    WHERE tc.city_id = :city_id AND {CATALOG_LISTED_SQL}
    GROUP BY p.specialist_role
    ORDER BY n DESC, p.specialist_role
    """
)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _window_bounds(now: datetime) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for key in _WINDOW_KEYS:
        tw = resolve_window(key, now)
        assert tw is not None
        out[f"{key}_from"] = tw.starts_at
        out[f"{key}_to"] = tw.ends_at
    return out


def _hhmm_in(hhmm: str, open_: str, close: str) -> bool:
    if close > open_:
        return open_ <= hhmm < close
    return hhmm >= open_ or hhmm < close


def open_state(opening_hours: Mapping[str, Any] | None, *, now: datetime, tz_name: str) -> dict[str, Any]:
    """``{"state": open|soon|closed|unknown, "close": "HH:MM"|None}`` по местному времени места."""
    hours = opening_hours if isinstance(opening_hours, Mapping) else {}
    if not has_known_hours(hours):
        return {"state": "unknown", "close": None}
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    local = now.astimezone(tz)
    hhmm = local.strftime("%H:%M")
    for open_, close in intervals_for_weekday(hours, local.weekday()):
        if _hhmm_in(hhmm, open_, close):
            close_norm = normalize_hhmm(close) or close
            ch, cm = int(close_norm[:2]), int(close_norm[3:5])
            minutes_left = (ch * 60 + cm) - (local.hour * 60 + local.minute)
            if minutes_left < 0:
                minutes_left += 24 * 60
            return {"state": "soon" if minutes_left <= _SOON_MINUTES else "open", "close": close_norm}
    return {"state": "closed", "close": None}


def _is_rink(venue_type: str) -> bool:
    return venue_type in (VENUE_TYPE_ICE, VENUE_TYPE_OUTDOOR)


def hot_window_key(counts: Mapping[str, int], *, now: datetime) -> str | None:
    """Какое окно подсветить: правило главной (пн–чт и пт до 15:00 — «сегодня», с пятницы
    15:00 и в выходные — «Сб–Вс», поздно вечером — «завтра»), если там есть сеансы;
    иначе первое непустое по порядку «сегодня → завтра → выходные»."""
    preferred = home_default_when_key(now)
    if preferred not in _WINDOW_KEYS:
        preferred = "today"
    order = [preferred] + [k for k in _WINDOW_KEYS if k != preferred]
    for key in order:
        if int(counts.get(key) or 0) > 0:
            return key
    return None


async def load_city_hub_view(
    session: AsyncSession,
    *,
    city: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(now or datetime.now(timezone.utc))
    city_id = int(city["id"])
    city_name = str(city["name"])
    scope = public_scope_params()

    count_rows = (
        (
            await session.execute(
                _WINDOW_COUNTS_SQL,
                {
                    "city_id": city_id,
                    "now": now,
                    "st": STATUS_ACTIVE,
                    **_window_bounds(now),
                    **scope,
                },
            )
        )
        .mappings()
        .all()
    )

    skate = {k: 0 for k in (*_WINDOW_KEYS, "all")}
    ohm = {k: 0 for k in (*_WINDOW_KEYS, "all")}
    skate_arenas: set[int] = set()
    ohm_arenas: set[int] = set()
    skate_by_arena: dict[int, int] = {}
    for row in count_rows:
        aid = int(row["arena_id"])
        target = ohm if row.get("is_ohm") else skate
        for key in (*_WINDOW_KEYS, "all"):
            target[key] += int(row.get(f"{key}_n") or 0)
        if int(row.get("all_n") or 0) > 0:
            (ohm_arenas if row.get("is_ohm") else skate_arenas).add(aid)
            if not row.get("is_ohm"):
                skate_by_arena[aid] = skate_by_arena.get(aid, 0) + int(row.get("all_n") or 0)

    upcoming_rows = (
        (
            await session.execute(
                _USER_UPCOMING_SQL,
                {
                    "user_city_id": city_id,
                    "starts_at": now,
                    "ends_at": now + timedelta(days=_UPCOMING_DAYS),
                    "now": now,
                    "st": STATUS_ACTIVE,
                    "lim": _UPCOMING_FETCH,
                    **scope,
                },
            )
        )
        .mappings()
        .all()
    )
    # Три ближайших — по разным каткам: три сеанса одного ТЦ подряд ничего не говорят о городе.
    upcoming: list[dict[str, Any]] = []
    seen_arenas: set[str] = set()
    for row in upcoming_rows:
        key = str(row.get("arena_slug") or row.get("arena_name") or "")
        if key in seen_arenas:
            continue
        seen_arenas.add(key)
        upcoming.append(_session_card(row, now=now))
        if len(upcoming) >= _UPCOMING_LIMIT:
            break

    next_ohm = None
    if ohm["all"]:
        row = (
            (
                await session.execute(
                    _NEXT_OHM_SQL,
                    {"city_id": city_id, "now": now, "st": STATUS_ACTIVE, **scope},
                )
            )
            .mappings()
            .first()
        )
        if row:
            next_ohm = dict(row)

    place_rows = (await session.execute(_PLACES_SQL, {"city_id": city_id, **scope})).mappings().all()
    places: list[dict[str, Any]] = []
    sharpening_month = now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).month
    for row in place_rows:
        hours = _as_mapping(row.get("opening_hours"))
        state = open_state(hours, now=now, tz_name=str(row.get("tz") or DEFAULT_TIMEZONE))
        raw_variants = row.get("photo_variants")
        if isinstance(raw_variants, str):
            raw_variants = json.loads(raw_variants)
        variants = _as_mapping(raw_variants)
        amenities = row.get("amenities")
        if isinstance(amenities, str):
            amenities = json.loads(amenities)
        places.append(
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "slug": str(row.get("slug") or ""),
                "venue_type": str(row.get("venue_type") or "ice"),
                "address": str(row.get("address") or ""),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "phone": str(row.get("phone") or ""),
                "website_url": str(row.get("website_url") or ""),
                "schedule_mode": str(row.get("schedule_mode") or "auto"),
                "amenities": amenities if isinstance(amenities, Mapping) else {},
                "photo_url": b_photo_url(variants.get("card")),
                "photo_hero": b_photo_url(variants.get("hero") or variants.get("card")),
                "photo_variants": dict(variants),
                "photo_width": int(row.get("photo_width") or 0),
                "display_tone": bool(row.get("display_tone")),
                "in_sharpening": row_in_sharpening_section(row, month=sharpening_month),
                "open_state": state["state"],
                "open_close": state["close"],
                "has_phone": bool(str(row.get("phone") or "").strip()),
            }
        )
    rinks = [p for p in places if _is_rink(p["venue_type"])]
    shops = [p for p in places if p["venue_type"] == VENUE_TYPE_SHOP]
    service_places = [p for p in places if p["in_sharpening"]]

    center_count = await city_hockey_center_count(session, city_id=city_id)
    trainer_rows = (await session.execute(_TRAINERS_SQL, {"city_id": city_id})).mappings().all()
    trainer_count = sum(int(r["n"] or 0) for r in trainer_rows)
    trainers: list[dict[str, Any]] = []
    if trainer_count:
        from src.application.site_trainers import CITY_TRAINERS_SHOWN, load_site_trainers

        trainers, _total = await load_site_trainers(session, city_id=city_id, limit=CITY_TRAINERS_SHOWN)
    roles: list[str] = []
    for r in trainer_rows:
        label = specialist_role_display(str(r.get("specialist_role") or "")).strip()
        if label and label.lower() not in [x.lower() for x in roles]:
            roles.append(label.lower())

    tz = ZoneInfo(DEFAULT_TIMEZONE)
    local_now = now.astimezone(tz)
    variant = choose_city_variant(places)
    week_rows: list[dict[str, Any]] = []
    nearby: list[dict[str, Any]] = []
    if variant == VARIANT_ONE:
        rink = next(p for p in places if p["venue_type"] in ("ice", "outdoor"))
        week_rows = await load_week(session, arena_id=int(rink["id"]), today=local_now.date(), now=now)
    origin = city_origin(places)
    if variant in (VARIANT_ONE, VARIANT_PHONE) and origin is not None:
        nearby = await load_nearby(
            session, city_id=city_id, origin=origin, today=local_now.date(), now=now
        )
    return {
        "city": dict(city),
        "slug": city_slug(city_name),
        "now": now,
        "local_now": local_now,
        "today": local_now.date(),
        "place_count": len(places),
        "rink_count": len(rinks),
        "shop_count": len(shops),
        "service_count": len(service_places),
        "skate_counts": skate,
        "skate_by_arena": skate_by_arena,
        "ohm_counts": ohm,
        "skate_arena_count": len(skate_arenas),
        "ohm_arena_count": len(ohm_arenas),
        "center_count": center_count,
        "upcoming": upcoming,
        "next_ohm": next_ohm,
        "places": places,
        "service_open": [p for p in service_places if p["open_state"] in ("open", "soon")],
        "shops_open": [p for p in shops if p["open_state"] in ("open", "soon")],
        "trainer_count": trainer_count,
        "trainer_roles": roles[:3],
        "trainers": trainers,
        "hot_skate": hot_window_key(skate, now=now),
        "hot_ohm": hot_window_key(ohm, now=now),
        "variant": variant,
        "week_rows": week_rows,
        "nearby": nearby,
    }


# ---------------------------------------------------------------------------
# Рендер
# ---------------------------------------------------------------------------


def _list_href(slug: str, **params: str | None) -> str:
    from urllib.parse import urlencode

    # Порядок как у selection_path: t, w, kind, seg, svc — одна и та же ссылка в хабе и в списке.
    order = ("t", "w", "kind", "seg", "svc")
    clean = {k: params[k] for k in order if params.get(k)}
    return f"/c/{slug}" + (("?" + urlencode(clean)) if clean else "")


def _session_when(card: Mapping[str, Any], *, today: date) -> tuple[str, str]:
    """(«22:15», «сегодня»/«завтра»/«сб, 11 окт»)."""
    starts = format_clock(str(card.get("starts_at_local") or ""))
    local_date = card.get("local_date")
    if isinstance(local_date, datetime):
        local_date = local_date.date()
    if not isinstance(local_date, date):
        return starts, ""
    rel = human_date(local_date, today=today)
    if rel in ("сегодня", "завтра"):
        return starts, rel
    wd = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")[local_date.weekday()]
    return starts, f"{wd}, {rel}"


def _price_bits(card: Mapping[str, Any]) -> str:
    currency = str(card.get("currency_code") or "BYN")
    bits: list[str] = []
    adult = card.get("price_adult_minor")
    if adult is not None:
        bits.append(format_price_minor(int(adult), currency))
    child = card.get("price_child_minor")
    if child is not None:
        bits.append(f"дети {format_price_minor(int(child), currency).replace(' ' + currency, '')}")
    if card.get("price_with_rental"):
        bits.append(str(card["price_with_rental"]))
    return " · ".join(bits)


def city_hub_document_title(view: Mapping[str, Any]) -> str:
    """Вкладка, og и заголовок в выдаче.

    Есть массовое катание — заголовок совпадает с запросом, которым город ищут:
    «массовое катание минск», «каток минск расписание». Иначе — разделы страницы.
    """
    city_name = format_public_name(str(view["city"]["name"]))
    where = city_locative(str(view["city"]["name"]))
    if where and int((view.get("skate_counts") or {}).get("all") or 0):
        return f"Массовое катание в {where} — расписание катков | Glide"
    bits: list[str] = []
    if int(view.get("rink_count") or 0):
        bits.append("где покататься")
    if int(view.get("service_count") or 0):
        bits.append("заточка")
    if int((view.get("ohm_counts") or {}).get("all") or 0) or int(view.get("center_count") or 0):
        bits.append(t("chip.hockey").lower())
    tail = ", ".join(bits) if bits else "места"
    return f"{city_name} · {tail} | Glide"


def city_hub_description(view: Mapping[str, Any]) -> str:
    """og:description считает места тем же ``place_count``, что и шапка страницы."""
    places = list(view.get("places") or [])
    n = int(view.get("place_count") if view.get("place_count") is not None else len(places))
    only_rinks = bool(places) and all(_is_rink(p["venue_type"]) for p in places)
    noun = ("каток", "катка", "катков") if only_rinks else ("место", "места", "мест")
    bits = [f"{n} {plural_ru(n, *noun)}"]
    sessions = int(view["skate_counts"].get("all") or 0)
    if sessions:
        bits.append(f"{sessions} {plural_ru(sessions, 'сеанс', 'сеанса', 'сеансов')}")
    return " · ".join(bits)


def city_hub_search_description(view: Mapping[str, Any]) -> str:
    """meta description для поисковика: фраза, которая не устаревает в его кэше.

    og:description остаётся счётом «N мест · M сеансов» — тем же, что в тексте шера.

    Счётчик сеансов меняется каждый час, а поисковик перечитывает страницу раз
    в несколько недель, поэтому здесь — что есть в городе, а не сколько сегодня.
    Катки называем по числу сеансов: первыми те, где льда больше всего.
    """
    raw_city = str(view["city"]["name"])
    city_name = format_public_name(raw_city)
    where = city_locative(raw_city)
    in_city = f"в {where}" if where else city_name
    by_arena = view.get("skate_by_arena") or {}
    rinks = [p for p in view.get("places") or [] if _is_rink(str(p.get("venue_type") or "ice"))]
    live = sorted(
        (p for p in rinks if int(by_arena.get(int(p["id"]), 0)) > 0),
        key=lambda p: (-int(by_arena.get(int(p["id"]), 0)), str(p.get("name") or "")),
    )
    sentences: list[str] = []
    if live:
        names = [format_public_name(str(p.get("name") or "")) for p in live[:3]]
        rest = len(rinks) - len(names)
        listed = ", ".join(names)
        if rest > 0:
            listed += f" и\u00a0ещё {rest}\u00a0{plural_ru(rest, 'каток', 'катка', 'катков')}"
        sentences.append(f"Массовое катание {in_city}: расписание сеансов на сегодня, завтра и выходные")
        sentences.append(f"{listed} — цены и адреса")
    elif rinks:
        n = len(rinks)
        sentences.append(f"{n}\u00a0{plural_ru(n, 'каток', 'катка', 'катков')} {in_city}: адреса, телефоны и часы работы")
    # ОХМ — свой запрос («охм минск»): список ОХМ закрыт от индекса, поэтому слово
    # должно быть хотя бы в сниппете города.
    ohm_n = int(view.get("ohm_arena_count") or 0) if int((view.get("ohm_counts") or {}).get("all") or 0) else 0
    if ohm_n:
        sentences.append(
            f"Открытые тренировки с клюшкой (ОХМ) — на {ohm_n}\u00a0{plural_ru(ohm_n, 'катке', 'катках', 'катках')}"
        )
    service_n = int(view.get("service_count") or 0)
    if service_n:
        sentences.append(f"Заточка коньков — {service_n}\u00a0{plural_ru(service_n, 'место', 'места', 'мест')}")
    if not sentences:
        return city_hub_description(view)
    return ". ".join(sentences) + "."


def _breadcrumbs(view: Mapping[str, Any], canonical_url: str) -> str:
    from src.application.place_links import breadcrumb_script

    name = format_public_name(str(view["city"]["name"]))
    return breadcrumb_script(canonical_url, [("Glide", "/"), (name, canonical_url)])


def city_hub_image_version(view: Mapping[str, Any]) -> str:
    raw = "|".join(
        (
            str(view.get("place_count")),
            str(view["skate_counts"].get("today")),
            str(view["skate_counts"].get("all")),
            str(view["ohm_counts"].get("all")),
            view["today"].isoformat(),
            "board2",
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def compose_city_hub_share(view: Mapping[str, Any], *, page_url: str) -> dict[str, str]:
    from src.application.client_share_message import share_body_for_native_share_dialog

    city_name = str(view["city"]["name"])
    lines = [f"{city_name} · где покататься", city_hub_description(view)]
    # Картинка показывает удобный срез (обычно вечер). Текст не перечисляет
    # три ближайших слота — они не совпадают с тем, что на билете.
    today_n = int((view.get("skate_counts") or {}).get("today") or 0)
    if today_n:
        word = plural_ru(today_n, "сеанс", "сеанса", "сеансов")
        lines.append(f"Сегодня {today_n} {word} — удобные часы на карточке")
    lines.append("Полный список — по ссылке")
    text_value = page_url + "\n\n" + "\n".join(lines)
    return {
        "share_url": page_url,
        "share_text": text_value,
        "share_body": share_body_for_native_share_dialog(text_value, page_url),
    }


def render_city_hub_page(
    view: Mapping[str, Any],
    *,
    canonical_url: str,
    og_image_url: str,
    cta_url: str | None,
    share: Mapping[str, str],
    story_image_url: str | None = None,
    base_url: str = "",
    trainers_href: str | None = None,
) -> str:
    city = view["city"]
    city_name = str(city["name"])
    city_id = int(city["id"])
    title = city_hub_document_title(view)
    description = city_hub_description(view)
    coach_href = trainers_href
    if coach_href is None:
        coach_href = public_telegram_cta_url(
            base_url,
            start_param=catalog_start_param(city_id, intent="coach"),
            surface="selection_page",
            city_id=city_id,
        )
    body = _b_body(
        view,
        base_url=base_url,
        cta_url=cta_url,
        share=share,
        story_image_url=story_image_url or og_image_url,
        coach_href=coach_href or "",
    )
    from src.application.catalog_list_share import catalog_list_share_tail
    from src.application.public_web_cta import phone_beacon_script

    body += phone_beacon_script(body)
    has_share_pick = int(view.get("rink_count") or 0) > 0
    need_share_js = bool(view.get("upcoming")) or has_share_pick
    share_tail = catalog_list_share_tail(scripts=need_share_js, css=has_share_pick)
    elements = []
    for p in view.get("places") or []:
        if not p.get("slug"):
            continue
        path = place_path(city_name=city_name, slug=p["slug"])
        elements.append(
            {
                "@type": "ListItem",
                "position": len(elements) + 1,
                "name": p["name"],
                "url": join_public_origin(canonical_url, path),
            }
        )
    ld = json_for_script(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": f"{city_name} · места для катания",
            "itemListElement": elements,
        }
    )
    from src.application.style_b import COMPONENTS_VERSION, STYLE_VERSION, TOKENS_VERSION

    lang, og_locale = html_lang_for_country(str(city.get("country") or ""))
    page = _B_TEMPLATE_PATH.read_text(encoding="utf-8")
    return fill_placeholders(
        page,
        {
            "__OG_TITLE__": _esc(title),
            "__OG_DESCRIPTION__": _esc(description),
            "__DESCRIPTION__": _esc(city_hub_search_description(view)),
            "__CANONICAL__": _esc(canonical_url),
            "__OG_URL__": _esc(share["share_url"]),
            "__OG_IMAGE__": _esc(og_image_url),
            "__LANG__": lang,
            "__OG_LOCALE__": og_locale,
            "__ROBOTS__": "index, follow",
            "__HEAD_EXTRA__": "",
            "__JSONLD__": ld,
            "__TOKENS_V__": TOKENS_VERSION,
            "__STYLE_V__": STYLE_VERSION,
            "__COMPONENTS_V__": COMPONENTS_VERSION,
            "__CITY_LINK__": "",
            "__BODY__": body + _breadcrumbs(view, canonical_url),
            **share_tail,
        },
    )


# ── TASK-246 · стиль B «Лёд и свет» (доски «B · Лёд и свет», «B · Кобрин», «B · Жлобин») ─────

_B_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "b.html"
_WEEKDAYS_FULL = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
_MONTHS_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def _b_today_kicker(view: Mapping[str, Any]) -> str:
    d = view["today"]
    return f"{_WEEKDAYS_FULL[d.weekday()]}, {d.day} {_MONTHS_GEN[d.month - 1]}"


def _b_counts_line(view: Mapping[str, Any]) -> str:
    today_n = int(view["skate_counts"].get("today") or 0)
    tomorrow_n = int(view["skate_counts"].get("tomorrow") or 0)
    weekend_n = int(view["skate_counts"].get("weekend") or 0)
    if today_n:
        word = plural_ru(today_n, "сеанс", "сеанса", "сеансов")
        line = f"Сегодня ещё {today_n} {word}"
        return line + (f", завтра — {tomorrow_n}" if tomorrow_n else "")
    if tomorrow_n:
        word = plural_ru(tomorrow_n, "сеанс", "сеанса", "сеансов")
        return f"Сегодня сеансов больше нет, завтра — {tomorrow_n} {word}"
    if weekend_n:
        word = plural_ru(weekend_n, "сеанс", "сеанса", "сеансов")
        return f"В выходные — {weekend_n} {word}"
    return ""


def _b_bar(view: Mapping[str, Any]) -> str:
    from src.application.style_b import brand_link, city_pill

    return brand_link() + city_pill("/#cities", format_public_name(str(view["city"]["name"])))


def _b_rinks(view: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [p for p in view.get("places") or [] if _is_rink(str(p.get("venue_type") or "ice"))]


def _b_upcoming(view: Mapping[str, Any]) -> str:
    from src.application.style_b import section, tile_html

    upcoming = list(view.get("upcoming") or [])
    if not upcoming:
        return ""
    slug = str(view["slug"])
    city_name = str(view["city"]["name"])
    today_n = int(view["skate_counts"].get("today") or 0)
    all_href = _list_href(slug, t="ice", w="today") if today_n else _list_href(slug, t="ice")
    by_slug = {str(p.get("slug") or ""): p for p in view.get("places") or []}
    tiles: list[str] = []
    from src.application.catalog_list_share import catalog_invite_link, invite_label_for_slot

    for card in upcoming:
        hhmm, day = _session_when(card, today=view["today"])
        arena_slug = str(card.get("arena_slug") or "").strip()
        href = place_path(city_name=city_name, slug=arena_slug) if arena_slug else "#"
        session_id = card.get("session_id")
        if session_id:
            href += f"?s={int(session_id)}"
        place = by_slug.get(arena_slug) or {}
        name = format_public_name(str(card.get("arena_name") or ""))
        badge = hhmm if day == "сегодня" else f"{day} {hhmm}"
        pv = place.get("photo_variants")
        tile = tile_html(
            href=href,
            name=name,
            line=_price_bits(card) or day,
            photo_url=place.get("photo_url"),
            photo_alt=name,
            toned=bool(place.get("display_tone")),
            badge=badge,
            badge_kind="time",
            photo_variants=pv if isinstance(pv, Mapping) else None,
        )
        arena_ref = place.get("id")
        if arena_ref is not None and session_id and href and href != "#":
            local_date = card.get("local_date")
            if hasattr(local_date, "year"):
                label = invite_label_for_slot(
                    {"local_date": local_date, "starts_at_local": card.get("starts_at_local")},
                    today=view["today"],
                )
            else:
                label = hhmm
            invite = catalog_invite_link(
                arena_ref=int(arena_ref),
                session_id=int(session_id),
                invite_label=label,
                place_name=name,
                fallback_href=href,
                css_class="b-tile__invite",
            )
            tile = f'<div class="b-tile-wrap">{invite}{tile}</div>'
        tiles.append(tile)
    more = f'<a class="b-more" href="{_esc(all_href)}">{_esc("Весь день" if today_n else "Все")}</a>'
    return section(
        t("hub.nearest_ice"),
        f'<div class="b-scroll">{"".join(tiles)}</div>',
        aside_html=more,
        klass="b-sec--flush",
    )


def _b_route_row(*, href: str, icon: str, title: str, line: str, quick: str = "") -> str:
    """Строка «Что нужно». Ссылка — на всю строку; окна времени — отдельные ссылки поверх неё."""
    from src.application.catalog_icons import icon_svg

    line_html = f'<span class="b-row__line">{line}</span>' if line else ""
    return (
        f'<div class="b-row" data-route="{_esc(title)}"><span class="b-row__icon">{icon_svg(icon)}</span>'
        f'<span class="b-row__body"><a class="b-row__title b-row__link" href="{_esc(href)}">{_esc(title)}</a>'
        f"{line_html}{quick}</span>"
        f'{icon_svg("chevron", extra_class="b-row__go")}</div>'
    )


def _b_quick(slug: str, counts: Mapping[str, int], *, all_count: int, hot: str | None, **base: str) -> str:
    """Окна «Сегодня · Завтра · В выходные · Все» со счётчиками. Ноль — не ссылка: «Завтра —»."""
    labels = {"today": t("when.today"), "tomorrow": t("when.tomorrow"), "weekend": t("when.weekend")}
    parts: list[str] = []
    for key in _WINDOW_KEYS:
        n = int(counts.get(key) or 0)
        if n <= 0:
            parts.append(f"<span>{_esc(labels[key])} <small>—</small></span>")
            continue
        cls = ' class="hot"' if key == hot else ""
        parts.append(f'<a{cls} href="{_esc(_list_href(slug, w=key, **base))}">{_esc(labels[key])} <small>{n}</small></a>')
    if all_count > 0:
        parts.append(f'<a href="{_esc(_list_href(slug, **base))}">Все <small>{all_count}</small></a>')
    return f'<span class="b-quick">{"".join(parts)}</span>'


def _b_open_line(places: list[Mapping[str, Any]], open_places: list[Mapping[str, Any]]) -> str:
    k = len(open_places)
    if not k:
        return ""
    word = "открыто" if k == 1 else "открыты"
    return f"{k} {word} сейчас"


def _b_routes(view: Mapping[str, Any], *, coach_href: str) -> str:
    from src.application.style_b import section

    slug = str(view["slug"])
    rows: list[str] = []
    rinks = int(view.get("rink_count") or 0)
    if rinks:
        counts = view["skate_counts"]
        all_n = int(counts.get("all") or 0)
        line = f"{rinks}\u00a0{plural_ru(rinks, 'каток', 'катка', 'катков')}"
        quick = ""
        if all_n:
            quick = _b_quick(slug, counts, all_count=all_n, hot=view.get("hot_skate"), t="ice")
        else:
            line += " · " + t("hub.no_skate_times")
        rows.append(_b_route_row(href=_list_href(slug, t="ice"), icon="skate", title=t("route.skate"), line=_esc(line), quick=quick))
    ohm = view["ohm_counts"]
    centers = int(view.get("center_count") or 0)
    if int(ohm.get("all") or 0):
        n = int(view.get("ohm_arena_count") or 0)
        bits = [f"ОХМ на {n} {plural_ru(n, 'катке', 'катках', 'катках')}"]
        nxt = view.get("next_ohm")
        if isinstance(nxt, Mapping):
            hhmm, day = _session_when(nxt, today=view["today"])
            bits.append(f"ближайший в {hhmm}" if day == "сегодня" else f"ближайший {day} в {hhmm}")
        quick = _b_quick(slug, ohm, all_count=int(ohm.get("all") or 0), hot=view.get("hot_ohm"), kind="ohm")
        rows.append(
            _b_route_row(
                href=_list_href(slug, kind="ohm"), icon="stick", title=t("chip.hockey"), line=_esc(" · ".join(bits)), quick=quick
            )
        )
    elif centers:
        line = f"{centers} {plural_ru(centers, 'центр', 'центра', 'центров')} по записи"
        rows.append(_b_route_row(href=_list_href(slug, kind="ohm", seg="centers"), icon="stick", title=t("chip.hockey"), line=_esc(line)))
    service_n = int(view.get("service_count") or 0)
    if service_n:
        service_places = [p for p in view.get("places") or [] if p.get("in_sharpening")]
        bits = [f"{service_n} {plural_ru(service_n, 'место', 'места', 'мест')}"]
        open_line = _b_open_line(service_places, list(view.get("service_open") or []))
        if open_line:
            bits.append(open_line)
        rows.append(_b_route_row(href=_list_href(slug, svc="service"), icon="sharpen", title=t("route.service"), line=_esc(" · ".join(bits))))
    shop_n = int(view.get("shop_count") or 0)
    if shop_n:
        shops = [p for p in view.get("places") or [] if p.get("venue_type") == VENUE_TYPE_SHOP]
        bits = [str(shop_n)]
        open_line = _b_open_line(shops, list(view.get("shops_open") or []))
        if open_line:
            bits.append(open_line)
        rows.append(_b_route_row(href=_list_href(slug, t="shop"), icon="shop", title=t("route.shops"), line=_esc(" · ".join(bits))))
    trainers = int(view.get("trainer_count") or 0)
    trainers_href = "#trainers" if view.get("trainers") else coach_href
    if trainers and trainers_href:
        line = f"{trainers} {plural_ru(trainers, 'тренер', 'тренера', 'тренеров')}"
        rows.append(_b_route_row(href=trainers_href, icon="person", title=t("route.trainers"), line=_esc(line)))
    if not rows:
        return ""
    return section(t("hub.what"), f'<div class="b-list">{"".join(rows)}</div>')


def _b_trainers(view: Mapping[str, Any], *, base_url: str, coach_href: str) -> str:
    """Тренеры города лицами (TASK-265); больше, чем показали, — «Все тренеры» в Telegram."""
    from src.application.place_links import public_telegram_cta_url, trainer_start_param
    from src.application.style_b import section, trainer_rows_html

    trainers = list(view.get("trainers") or [])
    if not trainers:
        return ""
    city_id = int(view["city"]["id"])

    def href_for(trainer: Mapping[str, Any]) -> str | None:
        return public_telegram_cta_url(
            base_url,
            start_param=trainer_start_param(int(trainer["id"])),
            surface="selection_page",
            city_id=city_id,
        )

    body = trainer_rows_html(trainers, href_for=href_for)
    total = int(view.get("trainer_count") or 0)
    if body and coach_href and total > len(trainers):
        body += f'<a class="b-more" href="{_esc(coach_href)}">{_esc(t("hub.trainers_all"))}</a>'
    return section(t("route.trainers"), body, sec_id="trainers")


def _b_all_places(view: Mapping[str, Any]) -> str:
    from src.application.catalog_icons import icon_svg

    places = list(view.get("places") or [])
    if len(places) < 2:
        return ""
    city_name = str(view["city"]["name"])
    groups: list[str] = []
    for title, group in (
        ("Катки", [p for p in places if _is_rink(p["venue_type"])]),
        ("Магазины и другие места", [p for p in places if not _is_rink(p["venue_type"])]),
    ):
        if not group:
            continue
        links = []
        for p in group:
            label = _esc(format_public_name(p["name"]))
            if p.get("slug"):
                links.append(f'<a href="{_esc(place_path(city_name=city_name, slug=p["slug"]))}">{label}</a>')
            else:
                links.append(label)
        groups.append(f"<p><b>{title}:</b> {', '.join(links)}</p>")
    return (
        '<section class="b-sec"><details class="b-details">'
        f'<summary>Все места города · {len(places)}{icon_svg("down")}</summary>'
        f'<div class="b-details__body">{"".join(groups)}</div></details></section>'
    )


def _b_nearby(view: Mapping[str, Any], *, title: str) -> str:
    from src.application.style_b import section, tile_html

    items = list(view.get("nearby") or [])
    if not items:
        return ""
    tiles = []
    for item in items:
        n = int(item.get("rink_count") or 0)
        name = format_public_name(str(item.get("name") or ""))
        line = f"{n} {plural_ru(n, 'каток', 'катка', 'катков')} · {item.get('when')} в {item.get('time')}"
        tiles.append(
            tile_html(
                href=f"/c/{city_slug(str(item.get('name') or ''))}",
                name=name,
                line=line,
                photo_url=item.get("photo_url"),
                photo_alt=name,
                toned=bool(item.get("display_tone")),
                badge=str(item.get("distance") or ""),
            )
        )
    more = f'<a class="b-more" href="/#cities">{_esc("Все города")}</a>'
    return section(title, f'<div class="b-scroll">{"".join(tiles)}</div>', aside_html=more, klass="b-sec--flush")


def _b_minutes_until(hhmm: str, now_local: datetime) -> int | None:
    try:
        h, m = (int(x) for x in hhmm.split(":")[:2])
    except ValueError:
        return None
    return h * 60 + m - (now_local.hour * 60 + now_local.minute)


def _b_soon(minutes: int) -> str:
    if minutes < 60:
        return f"через {minutes} мин"
    h, m = divmod(minutes, 60)
    return f"через {h} ч {m} мин" if m else f"через {h} ч"


def _b_one_today(view: Mapping[str, Any], rink: Mapping[str, Any]) -> str:
    from src.application.style_b import section

    today = view["today"]
    rows = [r for r in view.get("week_rows") or [] if r.get("local_date") == today]
    local_now = view["local_now"]
    tickets: list[str] = []
    marked = False
    href = place_path(city_name=str(view["city"]["name"]), slug=str(rink.get("slug") or "")) if rink.get("slug") else "#"
    for row in rows:
        start = format_clock(str(row.get("starts_at_local") or ""))
        end = format_clock(str(row.get("ends_at_local") or ""))
        minutes = _b_minutes_until(start, local_now)
        if minutes is not None and minutes < 0:
            continue
        sub = [f"до {end}"] if end else []
        klass = "b-ticket"
        if not marked and minutes is not None:
            marked = True
            klass += " b-ticket--dark"
            sub.append(_b_soon(minutes))
        sub_html = f'<span class="b-ticket__sub">{_esc(" · ".join(sub))}</span>' if sub else ""
        tickets.append(f'<a class="{klass}" href="{_esc(href)}"><span class="b-ticket__time">{_esc(start)}</span>{sub_html}</a>')
    amenities = rink.get("amenities") if isinstance(rink.get("amenities"), Mapping) else {}
    price = price_sentence(
        list(view.get("week_rows") or []),
        has_rental=bool(amenities.get("skate_rental")),
        has_sharpening=bool(amenities.get("skate_sharpening")),
    )
    price_html = f'<p class="b-text">{_esc(price)}.</p>' if price else ""
    if not tickets:
        if not price_html:
            return ""
        body = f'<p class="b-text">Сегодня сеансов больше нет.</p>{price_html}'
    else:
        body = f'<div class="b-tickets">{"".join(tickets)}</div>{price_html}'
    aside = f'<span class="b-aside">{_esc(_b_today_kicker(view))}</span>'
    return section(t("hub.today"), body, aside_html=aside)


def _b_one_week(view: Mapping[str, Any]) -> str:
    from src.application.style_b import section

    days = [d for d in week_days(list(view.get("week_rows") or []), today=view["today"]) if d["date"] != view["today"]]
    if not days:
        return ""
    rows = []
    for d in days:
        klass = "b-table__row b-table__row--end" if d["weekend"] else "b-table__row"
        label = d["label"]
        if label not in ("сегодня", "завтра"):
            label = f"{label}, {d['date'].day}"
        label = label[:1].upper() + label[1:]
        times = d["collapsed"] or " · ".join(d["times"])
        rows.append(
            f'<div class="{klass}"><span class="b-table__day">{_esc(label)}</span>'
            f'<span class="b-table__times">{_esc(times)}</span>'
            f'<span class="b-table__count">{len(d["times"])}</span></div>'
        )
    return section(t("hub.week"), f'<div class="b-table">{"".join(rows)}</div>')


def _b_rink_arrive(rink: Mapping[str, Any], *, base_url: str, city_id: int, show_phone_buttons: bool = True) -> str:
    from src.application.catalog_icons import icon_svg
    from src.application.public_web_cta import place_action_links
    from src.application.style_b import section

    links = place_action_links(rink, base_url=base_url, surface="selection_page", city_id=city_id)
    street = format_street_address(str(rink.get("address") or ""))
    head = ""
    if street:
        head = f'<div><b class="b-text" style="display:block;font-weight:600">{_esc(street)}</b>'
        head += f'<span class="b-note">{_esc(format_public_name(str(rink.get("name") or "")))}</span></div>'
    buttons = []
    if show_phone_buttons and links.get("tel"):
        buttons.append(
            f'<a class="b-btn" href="{_esc(links["tel"])}" data-catalog-phone-beacon="{_esc(links.get("tel_beacon"))}">'
            f'{icon_svg("phone")}{_esc(t("cta.call"))}</a>'
        )
    if links.get("route"):
        href, blank = links["route"]
        attrs = ' rel="noopener nofollow" target="_blank"' if blank else ' rel="nofollow"'
        buttons.append(f'<a class="b-btn" href="{_esc(href)}"{attrs}>{icon_svg("route")}{_esc(t("cta.route"))}</a>')
    if len(buttons) == 1:
        btn_html = buttons[0]
    else:
        btn_html = f'<div class="b-btns">{"".join(buttons)}</div>' if buttons else ""
    return section(t("hub.directions"), head + btn_html)


def _b_phone_block(view: Mapping[str, Any], rink: Mapping[str, Any], *, base_url: str) -> str:
    from src.application.catalog_icons import icon_svg
    from src.application.public_web_cta import place_action_links
    from src.application.style_b import section

    city_id = int(view["city"]["id"])
    links = place_action_links(rink, base_url=base_url, surface="selection_page", city_id=city_id)
    name = format_public_name(str(rink.get("name") or ""))
    calls: list[str] = []
    numbers = [n.strip() for n in str(rink.get("phone") or "").split(";") if n.strip()]
    for i, number in enumerate(numbers[:2]):
        if not is_valid_public_phone(number):
            continue
        klass = "b-call b-call--dark" if i == 0 else "b-call"
        calls.append(
            f'<a class="{klass}" href="tel:{_esc(tel_href(number))}" data-catalog-phone-beacon="{_esc(links.get("tel_beacon"))}">'
            f'{icon_svg("phone")}<span class="b-call__num">{_esc(format_phone_display(number))}</span></a>'
        )
    if not calls:
        return ""
    follow = ""
    if rink.get("id") is not None:
        href = public_telegram_cta_url(
            base_url,
            start_param=place_start_param(int(rink["id"])),
            surface="selection_page",
            city_id=city_id,
            arena_id=int(rink["id"]),
        )
        if href:
            follow = (
                f'<a class="b-follow" href="{_esc(href)}">{icon_svg("bell")}<span>'
                f'<b>{_esc(t("cta.follow_rink"))}</b><span>Напишем в Telegram, когда появится расписание</span></span></a>'
            )
    body = f'<p class="b-text">{_esc(t("hub.phone_when", name=name))}</p>' + "".join(calls) + follow
    return section(t("hub.when_title"), body)


def _b_body(
    view: Mapping[str, Any],
    *,
    base_url: str,
    cta_url: str | None,
    share: Mapping[str, str],
    story_image_url: str | None,
    coach_href: str,
) -> str:
    from src.application.style_b import hero_html, share_html

    city_name = format_public_name(str(view["city"]["name"]))
    city_id = int(view["city"]["id"])
    variant = str(view.get("variant") or "many")
    rinks = _b_rinks(view)
    with_photo = [p for p in rinks if p.get("photo_hero")]
    # Герой — самое крупное фото крытого катка: уличный каток и маленький кадр — запасные.
    with_photo.sort(key=lambda p: (str(p.get("venue_type")) != "ice", -int(p.get("photo_width") or 0)))
    hero_place = with_photo[0] if with_photo else None
    photo = hero_place.get("photo_hero") if hero_place else None
    hero_variants = hero_place.get("photo_variants") if hero_place else None
    if not isinstance(hero_variants, Mapping):
        hero_variants = None
    toned = bool(hero_place.get("display_tone")) if hero_place else False
    alt = format_public_name(str(hero_place.get("name") or "")) if hero_place else ""
    from src.application.catalog_list_share import catalog_selection_share_button, city_hub_share_endpoint

    share_pick = ""
    if int(view.get("rink_count") or 0) > 0:
        share_pick = catalog_selection_share_button(endpoint=city_hub_share_endpoint(view))
    share_block = share_pick + share_html(
        share, telegram_url=cta_url, story_image_url=story_image_url, telegram_link_only=True
    )
    if variant == VARIANT_ONE and rinks:
        rink = rinks[0]
        rink_name = format_public_name(str(rink.get("name") or ""))
        week_n = len(view.get("week_rows") or [])
        sub = rink_name
        if rink.get("slug"):
            href = place_path(city_name=str(view["city"]["name"]), slug=str(rink["slug"]))
            sub = f'<a href="{_esc(href)}">{_esc(rink_name)}</a>'
        else:
            sub = _esc(rink_name)
        if week_n:
            sub += f" · {week_n} {plural_ru(week_n, 'сеанс', 'сеанса', 'сеансов')} на этой неделе"
        rv = rink.get("photo_variants")
        hero = hero_html(
            title=t("hub.on_ice", city=city_name),
            title_break="на льду",
            sub_html=sub,
            photo_url=rink.get("photo_hero"),
            photo_alt=rink_name,
            toned=bool(rink.get("display_tone")),
            bar_html=_b_bar(view),
            photo_variants=rv if isinstance(rv, Mapping) else None,
        )
        return "".join(
            [
                hero,
                _b_one_today(view, rink),
                _b_one_week(view),
                _b_rink_arrive(rink, base_url=base_url, city_id=city_id),
                _b_nearby(view, title=t("hub.nearby")),
                _b_trainers(view, base_url=base_url, coach_href=coach_href),
                share_block,
            ]
        )
    if variant == VARIANT_PHONE and rinks:
        rink = rinks[0]
        rv = rink.get("photo_variants")
        hero = hero_html(
            title=t("hub.on_ice", city=city_name),
            title_break="на льду",
            sub_html=_esc(format_public_name(str(rink.get("name") or ""))) if len(rinks) == 1 else "",
            photo_url=rink.get("photo_hero"),
            photo_alt=format_public_name(str(rink.get("name") or "")),
            toned=bool(rink.get("display_tone")),
            bar_html=_b_bar(view),
            photo_variants=rv if isinstance(rv, Mapping) else None,
        )
        blocks = [hero]
        for r in rinks:
            blocks.append(_b_phone_block(view, r, base_url=base_url))
            blocks.append(_b_rink_arrive(r, base_url=base_url, city_id=city_id, show_phone_buttons=False))
        blocks.append(_b_nearby(view, title=t("hub.nearby_scheduled")))
        blocks.append(_b_trainers(view, base_url=base_url, coach_href=coach_href))
        blocks.append(share_block)
        return "".join(blocks)
    hero = hero_html(
        title=t("hub.on_ice", city=city_name),
            title_break="на льду",
        sub_html=_esc(_b_counts_line(view)),
        kicker=_b_today_kicker(view),
        photo_url=photo,
        photo_alt=alt,
        toned=toned,
        photo_variants=hero_variants,
        bar_html=_b_bar(view),
    )
    empty = ""
    if not view.get("places"):
        empty = '<section class="b-sec"><p class="b-text">В этом городе пока нет опубликованных мест.</p></section>'
    return "".join(
        [
            hero,
            _b_upcoming(view),
            _b_routes(view, coach_href=coach_href),
            empty,
            _b_all_places(view),
            _b_trainers(view, base_url=base_url, coach_href=coach_href),
            share_block,
        ]
    )
