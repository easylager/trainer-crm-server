"""
Публичная страница подборки ``/c/{город}?t=<тип>&w=<окно>`` (TASK-146).

То, чем делятся прямо из каталога: «Минск · где покататься на выходных», «Минск ·
магазины и заточка». Получатель видит ровно эту выборку — места, сеансы в окне с
ценами, ссылки на страницы мест — без Telegram и без установки. Кнопка «Открыть в
Telegram» ведёт в каталог с теми же фильтрами (``catalog_<город>_<тип>``).

Данные — те же, что в ленте мини-аппа (``list_public_ice_arenas``): одна правда для
приложения, страницы и картинки. Рендер — в общий шаблон страницы места
(``static/share/place.html``), чтобы подборка и место выглядели одной системой.
"""

from __future__ import annotations

import html as html_lib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import (
    _CURRENT_SESSION_SQL,
    STATUS_ACTIVE,
    list_public_ice_arenas,
)
from src.application.ice_city_day import city_slug, format_price_minor, plural_ru
from src.application.ice_time_windows import WHEN_KEYS
from src.application.place_links import place_path, place_query
from src.shared.venue_types import VENUE_TYPE_KEYS, has_public_skating

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "place.html"

#: Сколько мест и сеансов на месте показывает страница. Подборка — не справочник.
MAX_PLACES = 12
MAX_SLOTS_PER_PLACE = 4

_TOPIC = {
    None: "Где покататься",
    "ice": "Где покататься",
    "outdoor": "Уличный лёд",
    "shop": "Магазины и заточка",
    "gym": "Залы ОФП",
    "choreo": "Хореография",
    "pool": "Бассейны",
    "other": "Места для занятий",
}
_NOUNS = {
    "shop": ("место", "места", "мест"),
    "gym": ("зал", "зала", "залов"),
    "choreo": ("зал", "зала", "залов"),
    "pool": ("бассейн", "бассейна", "бассейнов"),
}


def clean_venue(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    return value if value in VENUE_TYPE_KEYS else None


def clean_when(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    return value if value in WHEN_KEYS and value not in ("any", "auto") else None


def selection_path(*, city_name: str, venue: str | None, when: str | None) -> str:
    params = {k: v for k, v in (("t", venue), ("w", when)) if v}
    return f"/c/{city_slug(city_name)}" + (("?" + urlencode(params)) if params else "")


def selection_image_path(*, city_name: str, venue: str | None, when: str | None) -> str:
    params = {k: v for k, v in (("t", venue), ("w", when)) if v}
    return f"/c/{city_slug(city_name)}/og.png" + (("?" + urlencode(params)) if params else "")


async def _window_slots(
    session: AsyncSession, arena_ids: list[int], window: Mapping[str, Any] | None, now: datetime
) -> dict[int, list[dict[str, Any]]]:
    """Сеансы мест в окне (или ближайшие, если окна нет) одним запросом."""
    if not arena_ids:
        return {}
    start = datetime.fromisoformat(window["from"]) if window else now
    end = datetime.fromisoformat(window["to"]) if window else None
    rows = (
        await session.execute(
            text(f"""
                SELECT s.id, s.arena_id, s.local_date, s.starts_at_local, s.price_adult_minor,
                       s.price_minor, s.currency_code
                FROM ice_sessions s
                WHERE s.arena_id = ANY(:ids)
                  AND {_CURRENT_SESSION_SQL}
                  AND s.starts_at_utc >= :start
                  AND (CAST(:end AS timestamptz) IS NULL OR s.starts_at_utc < CAST(:end AS timestamptz))
                ORDER BY s.starts_at_utc
                """),
            {"ids": arena_ids, "now": now, "start": start, "end": end, "st": STATUS_ACTIVE},
        )
    ).mappings()
    # Все сеансы окна (для честного счёта), показываем — первые MAX_SLOTS_PER_PLACE.
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r["arena_id"]), []).append(dict(r))
    return out


async def load_selection_view(
    session: AsyncSession,
    *,
    city: Mapping[str, Any],
    venue: str | None,
    when: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    skating = venue is None or has_public_skating(venue)
    listing = await list_public_ice_arenas(
        session,
        city_id=int(city["id"]),
        intent="skate",
        venue_type=venue,
        when=when if skating else None,
        limit=MAX_PLACES,
    )
    items = list(listing.get("items") or [])
    window = listing.get("window")
    slots = await _window_slots(session, [int(i["id"]) for i in items], window, now) if skating else {}
    # В окне — только места, где в окне есть лёд; пусто — честно показываем ближайшее.
    hits = [i for i in items if slots.get(int(i["id"]))] if window else items
    shown = hits or items
    return {
        "city": dict(city),
        "venue": venue,
        "when": when,
        "window": window,
        "window_empty": bool(window) and not hits,
        "items": shown[:MAX_PLACES],
        "slots": slots,
        "skating": skating,
        "session_count": sum(len(slots.get(int(i["id"]), [])) for i in shown[:MAX_PLACES]),
    }


def selection_title(view: Mapping[str, Any]) -> str:
    city = str(view["city"]["name"])
    topic = _TOPIC.get(view.get("venue"), "Места")
    window = view.get("window")
    if window and view.get("skating"):
        return f"{city} · {topic.lower()} — {str(window['label']).lower()}"
    return f"{city} · {topic.lower()}"


def selection_description(view: Mapping[str, Any]) -> str:
    items = view.get("items") or []
    n = len(items)
    venue = view.get("venue")
    noun = _NOUNS.get(venue or "", ("каток", "катка", "катков") if view.get("skating") else ("место", "места", "мест"))
    bits = [f"{n} {plural_ru(n, *noun)}"]
    sessions = int(view.get("session_count") or 0)
    if sessions:
        bits.append(f"{sessions} {plural_ru(sessions, 'сеанс', 'сеанса', 'сеансов')}")
    if view.get("window_empty"):
        bits.append(f"{str(view['window']['label']).lower()} сеансов нет — ближайшие")
    return " · ".join(bits)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _place_html(item: Mapping[str, Any], *, city_name: str, slots: list[dict[str, Any]]) -> str:
    slug = str(item.get("slug") or "")
    href = place_path(city_name=city_name, slug=slug) if slug else f"/p/{item['id']}"
    where = " · ".join(x for x in (item.get("district"), item.get("address")) if x)
    chips = ""
    rest = len(slots) - MAX_SLOTS_PER_PLACE
    for s in slots[:MAX_SLOTS_PER_PLACE]:
        hhmm = str(s.get("starts_at_local") or "")[:5]
        day = s.get("local_date")
        day_text = f"{day.day:02d}.{day.month:02d}" if hasattr(day, "day") else ""
        price = format_price_minor(
            s.get("price_adult_minor") if s.get("price_adult_minor") is not None else s.get("price_minor"),
            str(s.get("currency_code") or "BYN"),
        )
        chips += (
            f'<a class="slot" href="{_esc(href + place_query(session_id=int(s["id"])))}">'
            f'<span class="slot__time">{_esc(hhmm)}</span>'
            f'<span class="slot__price">{_esc(day_text)}{(" · " + _esc(price)) if price else ""}</span></a>'
        )
    if rest > 0:
        chips += f'<a class="slot slot--more" href="{_esc(href)}#schedule">ещё {rest}</a>'
    line = "" if chips else f'<p class="muted">{_esc(item.get("live_line") or "")}</p>'
    return (
        '<section class="sec">'
        f'<h2 class="pick__name"><a href="{_esc(href)}">{_esc(item.get("name"))}</a></h2>'
        + (f'<p class="pick__where">{_esc(where)}</p>' if where else "")
        + (f'<div class="slots">{chips}</div>' if chips else line)
        + "</section>"
    )


def render_selection_page(
    view: Mapping[str, Any],
    *,
    canonical_url: str,
    og_image_url: str,
    cta_url: str | None,
    share: Mapping[str, str],
    city_page_url: str | None,
    story_image_url: str | None = None,
) -> str:
    from src.application.place_page import _share_html  # общий ряд «Поделиться»

    city_name = str(view["city"]["name"])
    title = selection_title(view)
    description = selection_description(view)
    note = (
        f'<p class="plan__note pick__note">{_esc(view["window"]["label"])}: сеансов нет — показываем ближайшие.</p>'
        if view.get("window_empty")
        else ""
    )
    places = "".join(
        _place_html(i, city_name=city_name, slots=view["slots"].get(int(i["id"]), [])) for i in view["items"]
    )
    if not places:
        places = '<section class="sec"><p class="muted">В этой подборке пока пусто — загляните в каталог.</p></section>'
    hero = (
        '<header class="hero hero--ice">'
        f'<p class="hero__type">{_esc(view.get("window", {}) and view["window"]["label"] or "Подборка")}</p>'
        f'<h1 class="hero__title">{_esc(title)}</h1>'
        f'<p class="hero__where">{_esc(description)}</p>'
        "</header>"
    )
    dock = f'<div class="dock"><a class="cta" href="{_esc(cta_url)}">Открыть в Telegram</a></div>' if cta_url else ""
    body = hero + note + places + _share_html(share, venue_type="ice" if view.get("skating") else "shop") + dock
    ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": title,
            "itemListElement": [
                {"@type": "ListItem", "position": n + 1, "name": i.get("name")} for n, i in enumerate(view["items"])
            ],
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")
    page = _TEMPLATE_PATH.read_text(encoding="utf-8")
    city_link = f'<a href="{_esc(city_page_url)}">Весь лёд: {_esc(city_name)} сегодня</a>' if city_page_url else ""
    for key, value in {
        "__TITLE__": _esc(title),
        "__DESCRIPTION__": _esc(description),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_URL__": _esc(share["share_url"]),
        "__OG_IMAGE__": _esc(og_image_url),
        "__STORY_IMAGE__": _esc(story_image_url or og_image_url),
        "__ROBOTS__": "index, follow",
        "__JSONLD__": ld,
        "__CITY__": _esc(city_name),
        "__CITY_LINK__": city_link,
        "__TRUST__": "<p>Расписание — с сайтов катков и от администраций; время и цену уточняйте на месте.</p>",
        "__BODY__": body,
    }.items():
        page = page.replace(key, value)
    return page


def compose_selection_share(view: Mapping[str, Any], *, page_url: str) -> dict[str, str]:
    from src.application.client_share_message import share_body_for_native_share_dialog

    lines = [selection_title(view), selection_description(view)]
    for item in (view.get("items") or [])[:3]:
        slots = view["slots"].get(int(item["id"])) or []
        if slots:
            first = slots[0]
            lines.append(f"• {item.get('name')} — {str(first.get('starts_at_local') or '')[:5]}")
        else:
            lines.append(f"• {item.get('name')}")
    text_value = page_url + "\n\n" + "\n".join(lines)
    return {
        "share_url": page_url,
        "share_text": text_value,
        "share_body": share_body_for_native_share_dialog(text_value, page_url),
    }
