"""Волна 0: коды пустых состояний (§2/§3 empty-states-policy) и разметка для glide-track.js.

Только SSR/сайт. Mini App не трогаем. Серверные ``public_telegram_cta`` /
``public_contact_click`` остаются источником правды по кликам в БД; здесь — цели
Метрики/GA4 с теми же surface/action, без новой таблицы.
"""

from __future__ import annotations

import html as html_lib
import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping
from urllib.parse import quote

from src.shared.arena_schedule_mode import (
    SCHEDULE_MODE_PHONE,
    SCHEDULE_MODE_SEASON_CLOSED,
    normalize_schedule_mode,
)
from src.shared.config import get_settings
from src.shared.public_display import format_public_name
from src.shared.venue_types import has_public_skating

# Согласовано с public_web_cta / catalog_consumer_events.
# Согласовано с catalog_consumer_events / public_web_cta surfaces.
SURFACE_PLACE = "place_page"
SURFACE_CITY = "selection_page"
SURFACE_HOME = "catalog_home"

# Клиентские fallback (§6.2 + запрос волны 0): same_rink_day ≈ same_obj_day в политике.
FALLBACK_SAME_RINK_DAY = "same_rink_day"
FALLBACK_OTHER_RINK = "other_rink"
FALLBACK_NEARBY_CITY = "nearby_city"
FALLBACK_TRAINER = "trainer"
FALLBACK_CONTACT_PHONE = "contact_phone"
FALLBACK_CONTACT_SITE = "contact_site"

# Цели Метрики / имена GA4-событий (волна 0).
GOAL_ES_VIEW = "es_view"
GOAL_ES_FALLBACK_CLICK = "es_fallback_click"
GOAL_ES_WATCH_START = "es_watch_start"
GOAL_TICKET_BUY = "ticket_buy"
GOAL_TRAINER_CLICK = "trainer_click"
GOAL_TELEGRAM_CTA = "telegram_cta"

PLACE_PAGE_TYPE = "place"
CITY_PAGE_TYPE = "city"
HOME_PAGE_TYPE = "home"


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _session_dates(view: Mapping[str, Any]) -> list[date]:
    out: list[date] = []
    for day in view.get("days") or []:
        if not isinstance(day, Mapping):
            continue
        d = _as_date(day.get("local_date"))
        if d is None:
            continue
        if day.get("sessions"):
            out.append(d)
    return out


def _slot_count(view: Mapping[str, Any]) -> int:
    n = 0
    for day in view.get("days") or []:
        if isinstance(day, Mapping):
            n += len(day.get("sessions") or [])
    return n


def classify_place_state(view: Mapping[str, Any]) -> str:
    """Код P1…P13 для страницы катка. Порядок — §2 политики."""
    card = view.get("card") if isinstance(view.get("card"), Mapping) else {}
    mode = normalize_schedule_mode(card.get("schedule_mode"))
    today = _as_date(view.get("today")) or date.today()
    tracked = bool(card.get("schedule_tracked"))

    if mode == SCHEDULE_MODE_SEASON_CLOSED or card.get("in_season") is False:
        return "P9"

    amenities = card.get("amenities") if isinstance(card.get("amenities"), Mapping) else {}
    # P10 раньше P8: лёд без массового (hockey_center) — даже если mode=phone.
    if has_public_skating(card.get("venue_type")) and amenities.get("hockey_center") is True:
        return "P10"
    if str(card.get("venue_type") or "") == "shop":
        return "P1"

    if mode == SCHEDULE_MODE_PHONE:
        return "P8"

    slots = _slot_count(view)
    dates = _session_dates(view)
    horizon = _as_date(card.get("schedule_horizon"))
    if dates:
        last = max(dates)
        if horizon is None or horizon < last:
            horizon = last

    if slots == 0:
        if tracked:
            return "P6"
        return "P7"

    # P5: хвост — последний день в окне ≤ сегодня+2
    if horizon is not None and horizon <= today + timedelta(days=2):
        return "P5"

    if slots <= 2:
        return "P4"

    # P3: только сб/вс
    if dates and all(d.weekday() >= 5 for d in dates):
        return "P3"

    # P2: сегодня пуст, в другие дни недели есть
    if today not in dates and dates:
        return "P2"

    return "P1"


def place_track_context(view: Mapping[str, Any], *, state: str | None = None) -> dict[str, Any]:
    card = view.get("card") if isinstance(view.get("card"), Mapping) else {}
    st = state or classify_place_state(view)
    city = format_public_name(str(card.get("city_name") or card.get("city") or "").strip())
    ctx: dict[str, Any] = {
        "state": st,
        "page_type": PLACE_PAGE_TYPE,
        "city": city or None,
        "arena_id": int(card["id"]) if card.get("id") is not None else None,
        "city_id": int(card["city_id"]) if card.get("city_id") is not None else None,
    }
    return {k: v for k, v in ctx.items() if v is not None and v != ""}


def classify_city_state(view: Mapping[str, Any]) -> str:
    """Код C1…C8 для хаба города (§3.2). Упрощённо по уже загруженным полям view."""
    places = list(view.get("places") or [])
    if not places:
        return "C6"
    rink_count = int(view.get("rink_count") or len(places) or 0)
    skate_counts = view.get("skate_counts") if isinstance(view.get("skate_counts"), Mapping) else {}
    all_n = int(skate_counts.get("all") or 0)
    when = view.get("when")
    upcoming = list(view.get("upcoming") or [])
    trainers = list(view.get("trainers") or [])

    phone_only = all(
        normalize_schedule_mode(p.get("schedule_mode")) == SCHEDULE_MODE_PHONE
        for p in places
        if isinstance(p, Mapping)
    )
    if phone_only and places:
        return "C4"
    if rink_count <= 1:
        return "C3"
    if when and not upcoming and all_n > 0:
        return "C2"
    if not upcoming and all_n == 0:
        return "C5"
    if not trainers:
        # C7 — бедность поверх C1; для es_view оставляем основное состояние полного хаба.
        return "C1"
    return "C1"


def city_track_context(view: Mapping[str, Any], *, state: str | None = None) -> dict[str, Any]:
    city = view.get("city") if isinstance(view.get("city"), Mapping) else {}
    st = state or classify_city_state(view)
    name = format_public_name(str(city.get("name") or "").strip())
    ctx: dict[str, Any] = {
        "state": st,
        "page_type": CITY_PAGE_TYPE,
        "city": name or None,
        "city_id": int(city["id"]) if city.get("id") is not None else None,
    }
    return {k: v for k, v in ctx.items() if v is not None and v != ""}


def classify_home_state(view: Mapping[str, Any]) -> str:
    """H1…H3 для главной."""
    user_city = view.get("user_city")
    if not user_city:
        return "H3"
    skate = view.get("skate_counts") if isinstance(view.get("skate_counts"), Mapping) else {}
    if int(skate.get("today") or 0) <= 0 and int(view.get("today_sessions") or 0) <= 0:
        # «Сегодня нет» — H2; иначе H1.
        cities = list(view.get("cities") or [])
        today_any = any(int(c.get("today_n") or c.get("sessions_today") or 0) > 0 for c in cities if isinstance(c, Mapping))
        if not today_any:
            return "H2"
    return "H1"


def home_track_context(view: Mapping[str, Any], *, state: str | None = None) -> dict[str, Any]:
    st = state or classify_home_state(view)
    user_city = view.get("user_city") if isinstance(view.get("user_city"), Mapping) else None
    raw = str(user_city.get("name") or "").strip() if user_city else ""
    ctx: dict[str, Any] = {
        "state": st,
        "page_type": HOME_PAGE_TYPE,
        "city": format_public_name(raw) if raw else None,
        "city_id": int(user_city["id"]) if user_city and user_city.get("id") is not None else None,
    }
    return {k: v for k, v in ctx.items() if v is not None and v != ""}


def track_attrs(
    goal: str,
    *,
    fallback: str | None = None,
    action: str | None = None,
    target: str | None = None,
    pos: int | None = None,
    arena_id: int | None = None,
    state: str | None = None,
    surface: str | None = None,
) -> str:
    """HTML-атрибуты для ``<a …>`` — без ведущего пробела."""
    parts = [f'data-glide-track="{_esc(goal)}"']
    if fallback:
        parts.append(f'data-glide-fallback="{_esc(fallback)}"')
    if action:
        parts.append(f'data-glide-action="{_esc(action)}"')
    if target:
        parts.append(f'data-glide-target="{_esc(str(target)[:200])}"')
    if pos is not None:
        parts.append(f'data-glide-pos="{int(pos)}"')
    if arena_id is not None:
        parts.append(f'data-glide-arena-id="{int(arena_id)}"')
    if state:
        parts.append(f'data-glide-state="{_esc(state)}"')
    if surface:
        parts.append(f'data-glide-surface="{_esc(surface)}"')
    return " ".join(parts)


def glide_track_boot_html(context: Mapping[str, Any] | None) -> str:
    """JSON-контекст + script. Пустой context → только script (клики всё равно ловятся)."""
    settings = get_settings()
    ym = settings.yandex_metrika_counter_id
    ga = (settings.google_analytics_measurement_id or "").strip()
    attrs = ['src="/static/shared/glide-track.js"', "defer"]
    if ym and int(ym) > 0:
        attrs.append(f'data-ym-id="{int(ym)}"')
    if ga:
        attrs.append(f'data-ga-id="{_esc(ga)}"')
    script = "<script " + " ".join(attrs) + "></script>"
    if not context:
        return script
    payload = {k: v for k, v in dict(context).items() if v is not None and v != ""}
    # Числа оставляем числами; JSON в script type=application/json.
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (
        f'<script type="application/json" id="glide-es-context">{html_lib.escape(blob, quote=False)}</script>\n'
        f"  {script}"
    )


def track_query(goal: str, **params: Any) -> str:
    """Хвост query для отладки / документации (не обязателен в проде)."""
    q = [f"goal={quote(goal)}"]
    for k, v in params.items():
        if v is None or v == "":
            continue
        q.append(f"{quote(str(k))}={quote(str(v))}")
    return "&".join(q)
