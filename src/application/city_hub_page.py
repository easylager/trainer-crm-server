"""
Страница города ``/c/{город}`` без параметров — маршрутизатор потребностей (TASK-224).

Главная выбирает город; эта страница отвечает на вопрос «что нужно?» одним тапом:
плитка = потребность («Покататься», «Хоккей», «Заточка», «Магазины»,
«Тренеры»), под плиткой — живая строка и быстрые окна времени («Сегодня 3 · Завтра 24 ·
Сб–Вс 27»). Плитка без данных не показывается. Любой параметр (``?t=``, ``?w=``,
``?kind=``, ``?svc=``, ``?page=``) — это уже список (``selection_page``).

Макет: design/prototypes/2026-10-09-city-router-home.html, экран 1.
"""

from __future__ import annotations

import hashlib
import html as html_lib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_profile import has_known_hours, intervals_for_weekday, normalize_hhmm
from src.application.arena_public_use_cases import PLACE_SERVICE_KEYS, _OHM_SESSION_SQL, STATUS_ACTIVE
from src.application.catalog_home_page import _USER_UPCOMING_SQL, _format_date_string, _session_card
from src.application.ice_city_day import DEFAULT_TIMEZONE, city_slug, format_price_minor, human_date, plural_ru
from src.application.ice_time_windows import home_default_when_key, resolve_window
from src.application.place_links import catalog_start_param, join_public_origin, place_path, public_telegram_cta_url
from src.application.schedule_staleness import LEVEL_VERY_STALE, load_arena_freshness, staleness_level
from src.shared.catalog_visibility import CATALOG_LISTED_SQL
from src.shared.copy_ru import t
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.specialist_roles import specialist_role_display
from src.shared.venue_types import VENUE_TYPE_ICE, VENUE_TYPE_OUTDOOR, VENUE_TYPE_SHOP

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "place.html"
_CSS_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "city-hub.css"

_UPCOMING_DAYS = 7
_UPCOMING_LIMIT = 3
_UPCOMING_FETCH = 24
_WINDOW_KEYS = ("today", "tomorrow", "weekend")
_WINDOW_LABELS = {"today": "Сегодня", "tomorrow": "Завтра", "weekend": "Сб–Вс"}
#: Услуги, которые делают место «заточкой и прокатом» независимо от типа.
SERVICE_KEYS: tuple[str, ...] = PLACE_SERVICE_KEYS
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
      AND NOT (a.id = ANY(:very_stale_ids))
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
           p.slug, p.opening_hours, p.amenities, p.phone,
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
    arena_ids = sorted({int(r["arena_id"]) for r in count_rows})
    fresh = await load_arena_freshness(session, arena_ids, now=now) if arena_ids else {}
    very_stale = {aid for aid, item in fresh.items() if staleness_level(item) == LEVEL_VERY_STALE}

    skate = {k: 0 for k in (*_WINDOW_KEYS, "all")}
    ohm = {k: 0 for k in (*_WINDOW_KEYS, "all")}
    skate_arenas: set[int] = set()
    ohm_arenas: set[int] = set()
    for row in count_rows:
        aid = int(row["arena_id"])
        if aid in very_stale:
            continue
        target = ohm if row.get("is_ohm") else skate
        for key in (*_WINDOW_KEYS, "all"):
            target[key] += int(row.get(f"{key}_n") or 0)
        if int(row.get("all_n") or 0) > 0:
            (ohm_arenas if row.get("is_ohm") else skate_arenas).add(aid)

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
                    "very_stale_ids": sorted(very_stale) or [-1],
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
                    {"city_id": city_id, "now": now, "st": STATUS_ACTIVE, "very_stale_ids": sorted(very_stale) or [-1], **scope},
                )
            )
            .mappings()
            .first()
        )
        if row:
            next_ohm = dict(row)

    place_rows = (await session.execute(_PLACES_SQL, {"city_id": city_id, **scope})).mappings().all()
    places: list[dict[str, Any]] = []
    for row in place_rows:
        amenities = _as_mapping(row.get("amenities"))
        services = [k for k in SERVICE_KEYS if amenities.get(k) is True]
        hours = _as_mapping(row.get("opening_hours"))
        state = open_state(hours, now=now, tz_name=str(row.get("tz") or DEFAULT_TIMEZONE))
        places.append(
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "slug": str(row.get("slug") or ""),
                "venue_type": str(row.get("venue_type") or "ice"),
                "services": services,
                "open_state": state["state"],
                "open_close": state["close"],
                "has_phone": bool(str(row.get("phone") or "").strip()),
            }
        )
    rinks = [p for p in places if _is_rink(p["venue_type"])]
    shops = [p for p in places if p["venue_type"] == VENUE_TYPE_SHOP]
    service_places = [p for p in places if p["services"]]

    trainer_rows = (await session.execute(_TRAINERS_SQL, {"city_id": city_id})).mappings().all()
    trainer_count = sum(int(r["n"] or 0) for r in trainer_rows)
    roles: list[str] = []
    for r in trainer_rows:
        label = specialist_role_display(str(r.get("specialist_role") or "")).strip()
        if label and label.lower() not in [x.lower() for x in roles]:
            roles.append(label.lower())

    tz = ZoneInfo(DEFAULT_TIMEZONE)
    local_now = now.astimezone(tz)
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
        "ohm_counts": ohm,
        "skate_arena_count": len(skate_arenas),
        "ohm_arena_count": len(ohm_arenas),
        "upcoming": upcoming,
        "next_ohm": next_ohm,
        "places": places,
        "service_open": [p for p in service_places if p["open_state"] in ("open", "soon")],
        "shops_open": [p for p in shops if p["open_state"] in ("open", "soon")],
        "trainer_count": trainer_count,
        "trainer_roles": roles[:3],
        "hot_skate": hot_window_key(skate, now=now),
        "hot_ohm": hot_window_key(ohm, now=now),
    }


# ---------------------------------------------------------------------------
# Рендер
# ---------------------------------------------------------------------------


def _list_href(slug: str, **params: str | None) -> str:
    from urllib.parse import urlencode

    # Порядок как у selection_path: t, w, kind, svc — одна и та же ссылка в хабе и в списке.
    order = ("t", "w", "kind", "svc")
    clean = {k: params[k] for k in order if params.get(k)}
    return f"/c/{slug}" + (("?" + urlencode(clean)) if clean else "")


def _window_total(counts: Mapping[str, int]) -> int:
    return sum(int(counts.get(key) or 0) for key in _WINDOW_KEYS)


def _quick_html(slug: str, counts: Mapping[str, int], *, hot: str | None, all_count: int | None, **base: str) -> str:
    parts: list[str] = []
    for key in _WINDOW_KEYS:
        n = int(counts.get(key) or 0)
        label = _WINDOW_LABELS[key]
        if n <= 0:
            parts.append(f"<span>{label} <small>0</small></span>")
            continue
        cls = ' class="hot"' if key == hot else ""
        parts.append(f'<a{cls} href="{_esc(_list_href(slug, w=key, **base))}">{label} <small>{n}</small></a>')
    if all_count is not None and all_count > 0:
        parts.append(f'<a href="{_esc(_list_href(slug, **base))}">Все <small>{all_count}</small></a>')
    return '<div class="quick">' + "".join(parts) + "</div>"


def _route_html(*, href: str, name: str, count: str, live: str, dot_off: bool = False, quick: str = "") -> str:
    dot = '<span class="dot dot--off"></span>' if dot_off else '<span class="dot"></span>'
    live_html = f'<div class="live">{dot}{live}</div>' if live else ""
    return (
        '<article class="route">'
        f'<a class="t" href="{_esc(href)}"><span class="name">{_esc(name)}</span><span class="cnt">{_esc(count)}</span></a>'
        f"{live_html}{quick}</article>"
    )


def _session_when(card: Mapping[str, Any], *, today: date) -> tuple[str, str]:
    """(«22:15», «сегодня»/«завтра»/«сб, 11 окт»)."""
    starts = str(card.get("starts_at_local") or "").strip()[:5]
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


def _nearest_live(when: str, place: str, price: str) -> str:
    """Время и место — цветом текста, цена — тише, в хвосте."""
    fact = f'<span class="fact">ближайший <b>{_esc(when)} · {_esc(place)}</b></span>'
    if not price:
        return fact
    return fact + f' · <span class="price">{_esc(price)}</span>'


def _skate_route(view: Mapping[str, Any]) -> str:
    slug = str(view["slug"])
    counts = view["skate_counts"]
    rinks = int(view.get("rink_count") or 0)
    count = f"{rinks} {plural_ru(rinks, 'каток', 'катка', 'катков')}"
    live = ""
    upcoming = list(view.get("upcoming") or [])
    window_n = _window_total(counts)
    if upcoming:
        first = upcoming[0]
        hhmm, day = _session_when(first, today=view["today"])
        when = f"{day} {hhmm}".strip() if day != "сегодня" else hhmm
        price = _price_bits(first)
        live = _nearest_live(when, str(first.get("arena_name") or ""), price)
    elif window_n == 0:
        live = "ближайших сеансов нет"
    quick = "" if window_n == 0 else _quick_html(slug, counts, hot=view.get("hot_skate"), all_count=None, t="ice")
    return _route_html(href=_list_href(slug, t="ice"), name=t("route.skate"), count=count, live=live, dot_off=not upcoming, quick=quick)


def _ohm_route(view: Mapping[str, Any]) -> str:
    counts = view["ohm_counts"]
    if int(counts.get("all") or 0) <= 0:
        return ""
    slug = str(view["slug"])
    n = int(view.get("ohm_arena_count") or 0)
    count = f"{n} {plural_ru(n, 'каток', 'катка', 'катков')}"
    live = ""
    nxt = view.get("next_ohm")
    if isinstance(nxt, Mapping):
        hhmm, day = _session_when(nxt, today=view["today"])
        when = f"{day} {hhmm}".strip() if day != "сегодня" else hhmm
        price = format_price_minor(nxt.get("price_adult_minor"), str(nxt.get("currency_code") or "BYN"))
        live = _nearest_live(when, str(nxt.get("arena_name") or ""), price)
    quick = _quick_html(slug, counts, hot=view.get("hot_ohm"), all_count=int(counts.get("all") or 0), kind="ohm")
    return _route_html(href=_list_href(slug, kind="ohm"), name=t("chip.hockey"), count=count, live=live, quick=quick)


def _open_live(places: list[Mapping[str, Any]], open_places: list[Mapping[str, Any]]) -> tuple[str, bool]:
    """«4 открыты сейчас · ближайшее до 23:00 — Чижовка-арена» / «часы — на карточках». Второе — «точка погасла»."""
    if not places:
        return "", True
    k = len(open_places)
    if k:
        word = "открыто" if k == 1 else "открыты"
        bits = [f"<b>{k} {word} сейчас</b>"]
        with_close = sorted((p for p in open_places if p.get("open_close")), key=lambda p: str(p["open_close"]))
        if with_close:
            first = with_close[0]
            bits.append(f"ближайшее до {_esc(first['open_close'])} — {_esc(first['name'])}")
        return " · ".join(bits), False
    known = [p for p in places if p.get("open_state") == "closed"]
    if known and len(known) == len(places):
        return "сейчас закрыто · часы — на карточках", True
    return "часы работы — на карточках мест", True


def _service_route(view: Mapping[str, Any]) -> str:
    n = int(view.get("service_count") or 0)
    if n <= 0:
        return ""
    slug = str(view["slug"])
    service_places = [p for p in view.get("places") or [] if p.get("services")]
    live, off = _open_live(service_places, list(view.get("service_open") or []))
    count = f"{n} {plural_ru(n, 'место', 'места', 'мест')}"
    return _route_html(href=_list_href(slug, svc="service"), name=t("route.service"), count=count, live=live, dot_off=off)


def _shops_route(view: Mapping[str, Any]) -> str:
    n = int(view.get("shop_count") or 0)
    if n <= 0:
        return ""
    slug = str(view["slug"])
    shops = [p for p in view.get("places") or [] if p.get("venue_type") == VENUE_TYPE_SHOP]
    live, off = _open_live(shops, list(view.get("shops_open") or []))
    return _route_html(href=_list_href(slug, t="shop"), name=t("route.shops"), count=str(n), live=live, dot_off=off)


def _trainers_route(view: Mapping[str, Any], *, href: str) -> str:
    n = int(view.get("trainer_count") or 0)
    if n <= 0 or not href:
        return ""
    roles = list(view.get("trainer_roles") or [])
    live = _esc(", ".join(roles)) if roles else ""
    return _route_html(href=href, name=t("route.trainers"), count=str(n), live=live)


def _upcoming_html(view: Mapping[str, Any]) -> str:
    upcoming = list(view.get("upcoming") or [])
    if not upcoming:
        return ""
    slug = str(view["slug"])
    city_name = str(view["city"]["name"])
    today_n = int(view["skate_counts"].get("today") or 0)
    all_href = _list_href(slug, t="ice", w="today") if today_n else _list_href(slug, t="ice")
    all_label = "Все сегодня →" if today_n else "Все →"
    cards: list[str] = []
    for card in upcoming:
        hhmm, day = _session_when(card, today=view["today"])
        arena_slug = str(card.get("arena_slug") or "").strip()
        href = place_path(city_name=city_name, slug=arena_slug) if arena_slug else "#"
        if card.get("session_id"):
            href += f"?s={int(card['session_id'])}"
        sub_bits = [b for b in (_price_bits(card), str(card.get("basis_label") or "")) if b]
        cards.append(
            f'<a class="next__item" href="{_esc(href)}">'
            f'<span class="time">{_esc(hhmm)}<small>{_esc(day)}</small></span>'
            f'<span class="what"><b>{_esc(card.get("arena_name"))}</b>'
            + (f"<span>{_esc(' · '.join(sub_bits))}</span>" if sub_bits else "")
            + "</span></a>"
        )
    return (
        '<section class="hub-sec">'
        f'<div class="hub-head"><h2>Ближайшее на льду</h2><a href="{_esc(all_href)}">{all_label}</a></div>'
        f'<div class="next">{"".join(cards)}</div></section>'
    )


def _places_html(view: Mapping[str, Any]) -> str:
    places = list(view.get("places") or [])
    if not places:
        return ""
    city_name = str(view["city"]["name"])
    rinks = [p for p in places if _is_rink(p["venue_type"])]
    others = [p for p in places if not _is_rink(p["venue_type"])]
    parts: list[str] = []
    for title, group in (("Катки", rinks), ("Магазины и другие места", others)):
        if not group:
            continue
        links = ""
        for p in group:
            href = place_path(city_name=city_name, slug=p["slug"]) if p["slug"] else f"/p/{p['id']}"
            links += f'<li><a href="{_esc(href)}">{_esc(p["name"])}</a></li>'
        parts.append(f'<h3 class="places__title">{title}</h3><ul class="places__list">{links}</ul>')
    return '<section class="hub-sec hub-sec--places"><details class="places"><summary>Все места города</summary>' + "".join(parts) + "</details></section>"


def city_hub_document_title(view: Mapping[str, Any]) -> str:
    """Вкладка и og: только те разделы, которые на странице есть плиткой."""
    city_name = str(view["city"]["name"])
    bits: list[str] = []
    if int(view.get("rink_count") or 0):
        bits.append("где покататься")
    if int(view.get("service_count") or 0):
        bits.append("заточка")
    if int((view.get("ohm_counts") or {}).get("all") or 0):
        bits.append("хоккей")
    tail = ", ".join(bits) if bits else "места"
    return f"{city_name} · {tail} | Glide"


def city_hub_description(view: Mapping[str, Any]) -> str:
    """og:description хаба — та же фраза, что рисует /c/{город}/og.png и отдаёт share API подборки:
    «15 катков · 10 сеансов». Магазины в счёт «все места» не входят (TASK-217), слово —
    «катков», если без магазинов остались одни катки, иначе «мест»."""
    places = [p for p in view.get("places") or [] if p.get("venue_type") != VENUE_TYPE_SHOP]
    n = len(places)
    only_rinks = bool(places) and all(_is_rink(p["venue_type"]) for p in places)
    noun = ("каток", "катка", "катков") if only_rinks else ("место", "места", "мест")
    bits = [f"{n} {plural_ru(n, *noun)}"]
    sessions = int(view["skate_counts"].get("all") or 0)
    if sessions:
        bits.append(f"{sessions} {plural_ru(sessions, 'сеанс', 'сеанса', 'сеансов')}")
    return " · ".join(bits)


def _hero_sub(view: Mapping[str, Any]) -> str:
    n = int(view.get("place_count") or 0)
    head = f"{n} {plural_ru(n, 'место', 'места', 'мест')}."
    today_n = int(view["skate_counts"].get("today") or 0)
    tomorrow_n = int(view["skate_counts"].get("tomorrow") or 0)
    weekend_n = int(view["skate_counts"].get("weekend") or 0)
    if today_n:
        tail = f" <b>Сегодня на льду ещё {today_n} {plural_ru(today_n, 'сеанс', 'сеанса', 'сеансов')}</b>"
        tail += f", завтра — {tomorrow_n}." if tomorrow_n else "."
    elif tomorrow_n:
        tail = f" Сегодня сеансов больше нет, <b>завтра — {tomorrow_n}</b>."
    elif weekend_n:
        tail = f" <b>В выходные — {weekend_n} {plural_ru(weekend_n, 'сеанс', 'сеанса', 'сеансов')}</b>."
    else:
        tail = ""
    return head + tail


def city_hub_image_version(view: Mapping[str, Any]) -> str:
    raw = "|".join(
        (
            str(view.get("place_count")),
            str(view["skate_counts"].get("today")),
            str(view["skate_counts"].get("all")),
            str(view["ohm_counts"].get("all")),
            view["today"].isoformat(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def compose_city_hub_share(view: Mapping[str, Any], *, page_url: str) -> dict[str, str]:
    from src.application.client_share_message import share_body_for_native_share_dialog

    city_name = str(view["city"]["name"])
    lines = [f"{city_name} · где покататься", city_hub_description(view)]
    for card in list(view.get("upcoming") or [])[:3]:
        hhmm, day = _session_when(card, today=view["today"])
        lines.append(f"• {card.get('arena_name')} — {day} {hhmm}".replace("  ", " "))
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
    from src.application.place_page import _share_html
    from src.application.public_web_cta import render_generic_web_dock

    city = view["city"]
    city_name = str(city["name"])
    city_id = int(city["id"])
    local_now = view["local_now"]
    title = city_hub_document_title(view)
    description = city_hub_description(view)
    hero = (
        '<header class="hero hero--ice hub-hero">'
        f'<p class="hero__type">{_esc(_format_date_string(view["now"]))} · {local_now.strftime("%H:%M")}</p>'
        f'<h1 class="hero__title">{_esc(city_name)}</h1>'
        f'<p class="hero__where">{_hero_sub(view)}</p>'
        "</header>"
    )
    coach_href = trainers_href
    if coach_href is None:
        coach_href = public_telegram_cta_url(
            base_url,
            start_param=catalog_start_param(city_id, intent="coach"),
            surface="selection_page",
            city_id=city_id,
        )
    routes = "".join(
        x
        for x in (
            _skate_route(view) if int(view.get("rink_count") or 0) else "",
            _ohm_route(view),
            _service_route(view),
            _shops_route(view),
            _trainers_route(view, href=coach_href or ""),
        )
        if x
    )
    if routes:
        router = (
            '<section class="hub-sec"><h2>Что нужно?</h2>'
            f'<div class="router">{routes}</div>'
            '<p class="hub-hint">Лыжероллеры, залы и школы появятся здесь плитками, когда в городе будут данные. Пустых плиток не показываем.</p>'
            "</section>"
        )
    else:
        router = '<section class="hub-sec"><p class="muted">В этом городе пока нет опубликованных мест.</p></section>'
    dock = render_generic_web_dock(
        base_url=base_url,
        surface="selection_page",
        city_id=city_id,
        city_name=None,
        telegram_url=cta_url,
    )
    body = (
        hero
        + router
        + _upcoming_html(view)
        + _places_html(view)
        + _share_html(share, venue_type="ice", telegram_link_only=True)
        + dock
    )
    elements = []
    for n, p in enumerate(view.get("places") or []):
        path = place_path(city_name=city_name, slug=p["slug"]) if p.get("slug") else f"/p/{int(p['id'])}"
        elements.append({"@type": "ListItem", "position": n + 1, "name": p["name"], "url": join_public_origin(canonical_url, path)})
    ld = json_for_script(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": f"{city_name} · места для катания",
            "itemListElement": elements,
        }
    )
    css = _CSS_PATH.read_text(encoding="utf-8") if _CSS_PATH.exists() else ""
    lang, og_locale = html_lang_for_country(str(city.get("country") or ""))
    page = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return fill_placeholders(
        page,
        {
            "__OG_TITLE__": _esc(title),
            "__OG_DESCRIPTION__": _esc(description),
            "__CANONICAL__": _esc(canonical_url),
            "__OG_URL__": _esc(share["share_url"]),
            "__OG_IMAGE__": _esc(og_image_url),
            "__STORY_IMAGE__": _esc(story_image_url or og_image_url),
            "__LANG__": lang,
            "__OG_LOCALE__": og_locale,
            "__ROBOTS__": "index, follow",
            "__HEAD_EXTRA__": f"<style>{css}</style>" if css else "",
            "__JSONLD__": ld,
            "__CITY__": '<a href="/" class="hub-back">‹ Все города</a>',
            "__CITY_LINK__": "",
            "__TRUST__": "<p>Расписание — с сайтов катков и от администраций; время и цену уточняйте на месте.</p>",
            "__BODY__": body,
        },
    )
