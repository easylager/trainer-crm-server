"""
Публичная страница подборки ``/c/{город}?t=<тип>&w=<окно>`` (TASK-146).

То, чем делятся прямо из каталога: «Минск · где покататься на выходных», «Минск ·
магазины и заточка». Получатель видит ровно эту выборку — места, сеансы в окне с
ценами, ссылки на страницы мест — без Telegram и без установки. Кнопка «Открыть в
Telegram» ведёт в каталог с теми же фильтрами (``catalog_<город>_skate_<окно>``
или тип места). В чат и og уходят абсолютные даты, на странице — живая подпись окна.

Данные — те же, что в ленте мини-аппа (``list_public_ice_arenas``): одна правда для
приложения, страницы и картинки. Рендер — в общий шаблон страницы места
(``static/share/place.html``), чтобы подборка и место выглядели одной системой.
"""

from __future__ import annotations

import hashlib
import html as html_lib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import (
    CITY_SELECTION_PAGE_SIZE,
    _CURRENT_SESSION_SQL,
    STATUS_ACTIVE,
    city_selection_session_counts,
    city_selection_venue_types,
    list_city_selection_places,
    list_public_ice_arenas,
)
from src.application.ice_city_day import city_slug, format_price_minor, plural_ru
from src.application.ice_time_windows import WHEN_KEYS
from src.application.place_links import catalog_start_param, join_public_origin, place_path, place_query
from src.application.place_page import absolute_day_label
from src.application.schedule_staleness import (
    LEVEL_STALE,
    LEVEL_VERY_STALE,
    load_arena_freshness,
    stale_note,
    staleness_level,
    very_stale_note,
)
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.notification_hours import NOTIFICATION_TZ
from src.shared.phone_guard import is_valid_public_phone, tel_href
from src.shared.schedule_basis import public_basis_css_class
from src.shared.venue_types import DEFAULT_HIDDEN_VENUE_TYPES, VENUE_TYPE_KEYS, has_public_skating

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "place.html"

#: Сколько мест на странице города (пагинация).
MAX_PLACES = CITY_SELECTION_PAGE_SIZE
MAX_SLOTS_PER_PLACE = 4
# Без окна запрос раньше тянул все будущие сеансы. 64 на место хватает на чипы,
# «ещё N» и счёт в подписи; плотный уикенд (сеанс в час) сюда помещается.
_WINDOW_SLOTS_PER_ARENA = 64

_TOPIC = {
    None: "Все места",
    "ice": "Лёд",
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
    if value in ("ice", "gym", "shop"):
        return value
    return value if value in VENUE_TYPE_KEYS else None


def clean_page(raw: str | int | None) -> int:
    try:
        page = int(str(raw or "1").strip())
    except ValueError:
        return 1
    return page if page > 0 else 1


def clean_when(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    return value if value in WHEN_KEYS and value not in ("any", "auto") else None


def selection_path(
    *, city_name: str, venue: str | None, when: str | None, page: int | None = None
) -> str:
    params = {k: v for k, v in (("t", venue), ("w", when)) if v}
    if page is not None and int(page) > 1:
        params["page"] = str(int(page))
    return f"/c/{city_slug(city_name)}" + (("?" + urlencode(params)) if params else "")


def selection_image_path(
    *, city_name: str, venue: str | None, when: str | None, version: str | None = None
) -> str:
    """Путь картинки подборки. ``version`` — хэш данных: Telegram держит превью по URL."""
    params = {k: v for k, v in (("t", venue), ("w", when)) if v}
    if version:
        params["v"] = version
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
                       s.price_minor, s.currency_code, s.schedule_basis
                FROM arenas a
                JOIN LATERAL (
                    SELECT s.id, s.arena_id, s.local_date, s.starts_at_local, s.price_adult_minor,
                           s.price_minor, s.currency_code, s.schedule_basis, s.starts_at_utc
                    FROM ice_sessions s
                    WHERE s.arena_id = a.id
                      AND {_CURRENT_SESSION_SQL}
                      AND s.starts_at_utc >= :start
                      AND (CAST(:end AS timestamptz) IS NULL OR s.starts_at_utc < CAST(:end AS timestamptz))
                    ORDER BY s.starts_at_utc, s.id
                    LIMIT :cap
                ) s ON true
                WHERE a.id = ANY(:ids)
                ORDER BY s.starts_at_utc, s.id
                """),
            {
                "ids": arena_ids,
                "now": now,
                "start": start,
                "end": end,
                "st": STATUS_ACTIVE,
                "cap": _WINDOW_SLOTS_PER_ARENA,
            },
        )
    ).mappings()
    # До _WINDOW_SLOTS_PER_ARENA ближайших на место: чипы берут первые MAX_SLOTS_PER_PLACE,
    # остальное — «ещё N» и счёт в подписи.
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r["arena_id"]), []).append(dict(r))
    return out


async def _selection_session_totals(
    session: AsyncSession, counts: Mapping[int, int], *, now: datetime
) -> tuple[int, int]:
    """``(сеансов, мест с сеансами)`` по всей подборке — по местам, которые мы показываем.

    Место со «сверхстарым» расписанием (>72 ч) сеансов на странице не имеет: «не обновлялось
    N дней — уточните по телефону». В счёте его тоже нет — иначе превью обещает сеансы,
    которых человек не увидит.
    """
    if not counts:
        return 0, 0
    fresh = await load_arena_freshness(session, list(counts), now=now)
    sessions = 0
    places = 0
    for arena_id, n in counts.items():
        if staleness_level(fresh.get(int(arena_id))) == LEVEL_VERY_STALE:
            continue
        sessions += int(n)
        if int(n) > 0:
            places += 1
    return sessions, places


async def load_selection_view(
    session: AsyncSession,
    *,
    city: Mapping[str, Any],
    venue: str | None,
    when: str | None,
    page: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    page = clean_page(page)
    skating = venue is None or venue == "ice" or has_public_skating(venue)
    window = None
    filter_chips: list[dict[str, Any]] = []
    facets: list[dict[str, Any]] = []
    total = 0
    pages = 1
    if when:
        vtypes = city_selection_venue_types(venue)
        venue_param = ",".join(sorted(vtypes)) if vtypes else venue
        offset = (page - 1) * MAX_PLACES
        listing = await list_public_ice_arenas(
            session,
            city_id=int(city["id"]),
            intent="skate",
            venue_type=venue_param,
            when=when if skating else None,
            limit=MAX_PLACES,
            cursor=str(offset) if offset else None,
        )
        items = list(listing.get("items") or [])
        window = listing.get("window")
        total = int(listing.get("total") or len(items))
        pages = max(1, (total + MAX_PLACES - 1) // MAX_PLACES)
        filter_chips = []
        facets = list(listing.get("venue_type_facets") or [])
    else:
        catalog = await list_city_selection_places(
            session,
            city_id=int(city["id"]),
            venue_types=city_selection_venue_types(venue),
            page=page,
            now=now,
        )
        items = list(catalog.get("items") or [])
        total = int(catalog.get("total") or 0)
        pages = int(catalog.get("pages") or 1)
        filter_chips = list(catalog.get("filter_chips") or [])
        facets = list(catalog.get("venue_type_facets") or [])
    slots = await _window_slots(session, [int(i["id"]) for i in items], window, now) if skating else {}
    # TASK-180: свежесть расписания на момент ``now``. > 6 ч — строка «могло измениться»;
    # > 72 ч — сеансы места не показываем и не считаем: «не обновлялось N дней — уточните».
    stale_notes: dict[int, str] = {}
    unconfirmed_notes: dict[int, str] = {}
    if skating and items:
        fresh = await load_arena_freshness(session, [int(i["id"]) for i in items], now=now)
        for item in items:
            aid = int(item["id"])
            level = staleness_level(fresh.get(aid))
            if level == LEVEL_STALE and slots.get(aid):
                stale_notes[aid] = stale_note(fresh.get(aid), now=now)
            elif level == LEVEL_VERY_STALE:
                slots.pop(aid, None)
                unconfirmed_notes[aid] = very_stale_note(
                    fresh.get(aid),
                    now=now,
                    has_phone=bool(str(item.get("phone") or "").strip()),
                    has_site=bool(str(item.get("tickets_url") or item.get("website_url") or "").strip()),
                )
    # В окне — только места, где в окне есть лёд; пусто — честно показываем ближайшее.
    hits = [i for i in items if slots.get(int(i["id"]))] if window else items
    shown = hits or items
    shown_page = shown[:MAX_PLACES]
    # Счёт для превью — по всей подборке, а не по странице: один агрегат вместо len(shown_page).
    selection_counts = (
        await city_selection_session_counts(
            session,
            city_id=int(city["id"]),
            venue_types=city_selection_venue_types(venue),
            window=window,
            now=now,
        )
        if skating
        else {}
    )
    session_total, window_places = await _selection_session_totals(session, selection_counts, now=now)
    return {
        "city": dict(city),
        "venue": venue,
        "when": when,
        "page": page,
        "pages": pages,
        "total": total,
        "filter_chips": filter_chips,
        "window": window,
        "window_empty": bool(window) and not hits,
        "items": shown_page,
        "slots": slots,
        "stale_notes": stale_notes,
        "unconfirmed_notes": unconfirmed_notes,
        "skating": skating,
        "session_count": session_total,
        # Места с сеансом в окне — по всей выборке: это число обещает заголовок.
        "window_places": window_places,
        # Фасеты всего города: по ним выбирается слово «катков»/«мест», а не по странице.
        "venue_type_facets": facets,
    }


def selection_title(view: Mapping[str, Any]) -> str:
    city = str(view["city"]["name"])
    topic = _TOPIC.get(view.get("venue"), "Места")
    window = view.get("window")
    if window and view.get("skating"):
        return f"{city} · {topic.lower()} — {str(window['label']).lower()}"
    return f"{city} · {topic.lower()}"


def absolute_window_phrase(window: Mapping[str, Any] | None) -> str:
    """«Пт, 3 окт, вечер» / «Сб, 4 окт – Вс, 5 окт». Без «сегодня»: превью живёт в чате сутками."""
    if not window or not window.get("from") or not window.get("to"):
        return ""
    tz = ZoneInfo(NOTIFICATION_TZ)
    start = datetime.fromisoformat(str(window["from"])).astimezone(tz).date()
    end = datetime.fromisoformat(str(window["to"])).astimezone(tz).date() - timedelta(days=1)
    if end < start:
        end = start
    key = str(window.get("key") or "")
    if key == "weekend" and end != start:
        return f"{absolute_day_label(start)} – {absolute_day_label(end)}"
    phrase = absolute_day_label(start)
    if key == "today_evening":
        return f"{phrase}, вечер"
    return phrase


def selection_share_title(view: Mapping[str, Any]) -> str:
    """Заголовок для og и текста в чате: те же факты, что на странице, но даты абсолютные."""
    city = str(view["city"]["name"])
    topic = _TOPIC.get(view.get("venue"), "Места")
    window = view.get("window")
    if window and view.get("skating"):
        phrase = absolute_window_phrase(window)
        if phrase:
            return f"{city} · {topic.lower()} — {phrase}"
    return f"{city} · {topic.lower()}"


def selection_count_noun(view: Mapping[str, Any]) -> tuple[str, str, str]:
    """Слово при счётчике — по всему городу, а не по странице.

    Явный чип — его существительное. Без чипа смотрим фасеты города: одни катки —
    «катков», есть залы или места — «мест». Раньше слово считалось по 12 карточкам
    страницы, и подборка «все места» называла катками город, где катков — половина.
    """
    venue = view.get("venue")
    if venue in ("ice", "outdoor"):
        return ("каток", "катка", "катков")
    if venue in _NOUNS:
        return _NOUNS[venue]
    if venue:
        return ("место", "места", "мест")
    facet_keys = [str(facet.get("key") or "") for facet in view.get("venue_type_facets") or []]
    if facet_keys:
        # Магазины в подборку «все места» не входят — и слова не портят (TASK-217).
        kinds = {"ice" if key in ("ice", "outdoor") else key for key in facet_keys if key}
        kinds -= DEFAULT_HIDDEN_VENUE_TYPES
        return ("каток", "катка", "катков") if kinds == {"ice"} else ("место", "места", "мест")
    nouns: list[tuple[str, str, str]] = []
    for item in view.get("items") or []:
        key = str(item.get("venue_type") or "ice")
        if key in ("ice", "outdoor"):
            nouns.append(("каток", "катка", "катков"))
        else:
            nouns.append(_NOUNS.get(key, ("место", "места", "мест")))
    if not nouns:
        return ("место", "места", "мест")
    if all(noun[0] == nouns[0][0] for noun in nouns):
        return nouns[0]
    return ("место", "места", "мест")


def selection_place_count(view: Mapping[str, Any]) -> int:
    """Сколько мест в подборке целиком — не страница.

    Без окна — вся выборка города. С ``?w=`` — места, у которых в окне есть сеанс:
    ровно то, что обещает заголовок. Пустое окно честно падает на всю выборку
    («сеансов нет — ближайшие»), иначе в превью стоял бы ноль при непустом списке.
    """
    if view.get("when"):
        in_window = int(view.get("window_places") or 0)
        if in_window:
            return in_window
    return int(view.get("total") or 0)


def selection_description(view: Mapping[str, Any]) -> str:
    n = selection_place_count(view)
    noun = selection_count_noun(view)
    bits = [f"{n} {plural_ru(n, *noun)}"]
    sessions = int(view.get("session_count") or 0)
    if sessions:
        bits.append(f"{sessions} {plural_ru(sessions, 'сеанс', 'сеанса', 'сеансов')}")
    if view.get("window_empty"):
        bits.append(f"{str(view['window']['label']).lower()} сеансов нет — ближайшие")
    return " · ".join(bits)


def _minsk_day(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(NOTIFICATION_TZ)).date()


def _view_slots(view: Mapping[str, Any], item: Mapping[str, Any]) -> list[Any]:
    slots = view.get("slots") or {}
    found = slots.get(int(item["id"]))
    if found is None:
        found = slots.get(str(item["id"]))
    return list(found or [])


def selection_share_places(
    view: Mapping[str, Any], *, today: date | None = None
) -> list[tuple[Mapping[str, Any], list[Any]]]:
    """Порядок строк «Ссылка»/«Другое» и подписи og.png: сегодняшние сеансы — первыми.

    Сначала места с сеансом на сегодня по Минску — по времени начала, потом остальные
    по названию. В порядке страницы далёкий каток, случайно оказавшийся выше, забирал
    одну из трёх строк у того, где есть лёд сегодня.
    """
    day = today or _minsk_day()
    with_today: list[tuple[date, str, Mapping[str, Any], list[Any]]] = []
    others: list[tuple[str, Mapping[str, Any], list[Any]]] = []
    for item in view.get("items") or []:
        slots = _view_slots(view, item)
        first = slots[0] if slots else None
        local_date = first.get("local_date") if isinstance(first, Mapping) else None
        if isinstance(local_date, datetime):
            local_date = local_date.date()
        if first is not None and local_date == day:
            hhmm = str(first.get("starts_at_local") or "")[:5]
            with_today.append((local_date, hhmm, item, slots))
        else:
            others.append((str(item.get("name") or "").casefold(), item, slots))
    with_today.sort(key=lambda row: (row[0], row[1]))
    others.sort(key=lambda row: row[0])
    return [(item, slots) for _day, _hhmm, item, slots in with_today] + [
        (item, slots) for _name, item, slots in others
    ]


def selection_image_version(view: Mapping[str, Any]) -> str:
    """Короткий хэш данных превью: Telegram держит старую картинку по URL.

    В хэш входят ровно те числа, что человек видит на картинке, и день по Минску:
    расписание меняется внутри дня, и превью обязано перечитаться.
    """
    raw = "|".join(
        (
            str(selection_place_count(view)),
            str(int(view.get("session_count") or 0)),
            _minsk_day().isoformat(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def selection_share_description(view: Mapping[str, Any]) -> str:
    """og:description. Пустое окно называет даты, а не «сегодня вечером»."""
    text = selection_description(view)
    window = view.get("window")
    if view.get("window_empty") and window:
        live = f"{str(window['label']).lower()} сеансов нет — ближайшие"
        phrase = absolute_window_phrase(window)
        if phrase and live in text:
            text = text.replace(live, f"{phrase}: сеансов нет — ближайшие")
    return text


_LINK_VENUES = frozenset({"shop", "gym", "ice", "outdoor", "choreo", "pool", "other"})
_LINK_SKATING = frozenset({"skate", "ice", "outdoor"})


def selection_start_param(*, city_id: int, venue: str | None, when: str | None) -> str:
    """startapp с тем же типом места и окном, что на странице подборки."""
    if venue in _LINK_VENUES:
        token: str | None = venue
    elif venue is None or has_public_skating(venue):
        token = "skate"
    else:
        token = None
    link_when = when if token in _LINK_SKATING else None
    return catalog_start_param(int(city_id), token, link_when)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _place_photo_url(item: Mapping[str, Any]) -> str | None:
    """Тот же кадр, что в мини-карточке каталога. Нет URL — нет фото-блока."""
    for key in ("card", "thumb"):
        url = str(item.get(key) or "").strip()
        if url.lower().startswith(("https://", "http://", "/")):
            return url
    return None


def _phone_link(item: Mapping[str, Any]) -> str:
    phone = str(item.get("phone") or "").strip()
    if phone and is_valid_public_phone(phone):
        return f' <a href="tel:{_esc(tel_href(phone))}">{_esc(phone)}</a>'
    return ""


def _place_html(
    item: Mapping[str, Any],
    *,
    city_name: str,
    slots: list[dict[str, Any]],
    stale: str = "",
    unconfirmed: str = "",
) -> str:
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
        basis_cls = public_basis_css_class(str(s.get("schedule_basis") or "live"))
        slot_cls = "slot" + (f" {basis_cls}" if basis_cls else "")
        chips += (
            f'<a class="{_esc(slot_cls)}" href="{_esc(href + place_query(session_id=int(s["id"])))}">'
            f'<span class="slot__time">{_esc(hhmm)}</span>'
            f'<span class="slot__price">{_esc(day_text)}{(" · " + _esc(price)) if price else ""}</span></a>'
        )
    if rest > 0:
        chips += f'<a class="slot slot--more" href="{_esc(href)}#schedule">ещё {rest}</a>'
    line = "" if chips else f'<p class="muted">{_esc(item.get("live_line") or "")}</p>'
    if unconfirmed:
        # TASK-180: > 72 ч без подтверждения — не расписание, а просьба уточнить.
        line = f'<p class="pick__stale">{_esc(unconfirmed)}{_phone_link(item)}</p>'
    # TASK-180: > 6 ч — сеансы показываем, но над ними спокойная строка «могло измениться».
    stale_html = f'<p class="pick__stale">{_esc(stale)}</p>' if stale and chips else ""
    photo = _place_photo_url(item)
    icon = str(item.get("venue_icon") or "").strip()
    if photo:
        media = (
            f'<a class="pick__media" href="{_esc(href)}" data-icon="{_esc(icon)}">'
            f'<img class="pick__photo" src="{_esc(photo)}" alt="" loading="lazy" decoding="async" />'
            f"</a>"
        )
    else:
        media = f'<span class="pick__icon" aria-hidden="true">{_esc(icon)}</span>' if icon else ""
    return (
        '<section class="sec pick">'
        '<div class="pick__head">'
        + media
        + '<div class="pick__titles">'
        + f'<h2 class="pick__name"><a href="{_esc(href)}">{_esc(item.get("name"))}</a></h2>'
        + (f'<p class="pick__where">{_esc(where)}</p>' if where else "")
        + "</div></div>"
        + (stale_html + f'<div class="slots">{chips}</div>' if chips else line)
        + "</section>"
    )


def _filter_chips_html(view: Mapping[str, Any], *, city_name: str) -> str:
    chips = list(view.get("filter_chips") or [])
    if not chips or view.get("when"):
        return ""
    active = str(view.get("venue") or "")
    parts = []
    all_href = selection_path(city_name=city_name, venue=None, when=None, page=1)
    all_cls = "chip" + (" chip--on" if not active else "")
    parts.append(f'<a class="{all_cls}" href="{_esc(all_href)}">Все</a>')
    for chip in chips:
        key = str(chip.get("key") or "")
        label = str(chip.get("label") or key)
        href = selection_path(city_name=city_name, venue=key, when=None, page=1)
        cls = "chip" + (" chip--on" if active == key else "")
        parts.append(f'<a class="{cls}" href="{_esc(href)}">{_esc(label)}</a>')
    return '<nav class="chips" aria-label="Тип места">' + "".join(parts) + "</nav>"


def _pagination_html(view: Mapping[str, Any], *, city_name: str, canonical_base: str) -> str:
    pages = int(view.get("pages") or 1)
    page = int(view.get("page") or 1)
    if pages <= 1:
        return ""
    venue, when = view.get("venue"), view.get("when")
    prev_href = (
        selection_path(city_name=city_name, venue=venue, when=when, page=page - 1) if page > 1 else None
    )
    next_href = (
        selection_path(city_name=city_name, venue=venue, when=when, page=page + 1) if page < pages else None
    )
    bits = [f'<p class="muted">Страница {page} из {pages}</p>']
    if prev_href:
        bits.append(f'<a rel="prev" href="{_esc(prev_href)}">Назад</a>')
    if next_href:
        bits.append(f'<a rel="next" href="{_esc(next_href)}">Дальше</a>')
    return '<nav class="pager" aria-label="Страницы">' + " · ".join(bits) + "</nav>"


def _head_links_html(view: Mapping[str, Any], *, city_name: str, canonical_base: str) -> str:
    pages = int(view.get("pages") or 1)
    page = int(view.get("page") or 1)
    if pages <= 1:
        return ""
    venue, when = view.get("venue"), view.get("when")
    links = []
    if page > 1:
        prev = selection_path(city_name=city_name, venue=venue, when=when, page=page - 1)
        links.append(f'<link rel="prev" href="{_esc(join_public_origin(canonical_base, prev))}" />')
    if page < pages:
        nxt = selection_path(city_name=city_name, venue=venue, when=when, page=page + 1)
        links.append(f'<link rel="next" href="{_esc(join_public_origin(canonical_base, nxt))}" />')
    return "".join(links)


def render_selection_page(
    view: Mapping[str, Any],
    *,
    canonical_url: str,
    og_image_url: str,
    cta_url: str | None,
    share: Mapping[str, str],
    city_page_url: str | None,
    story_image_url: str | None = None,
    base_url: str = "",
) -> str:
    from src.application.place_page import _share_html  # общий ряд «Поделиться»
    from src.application.public_web_cta import render_generic_web_dock

    city_name = str(view["city"]["name"])
    title = selection_title(view)
    share_title = selection_share_title(view)
    description = selection_description(view)
    share_description = selection_share_description(view)
    note = (
        f'<p class="plan__note pick__note">{_esc(view["window"]["label"])}: сеансов нет — показываем ближайшие.</p>'
        if view.get("window_empty")
        else ""
    )
    stale_notes = view.get("stale_notes") or {}
    unconfirmed_notes = view.get("unconfirmed_notes") or {}
    places = "".join(
        _place_html(
            i,
            city_name=city_name,
            slots=view["slots"].get(int(i["id"]), []),
            stale=stale_notes.get(int(i["id"]), ""),
            unconfirmed=unconfirmed_notes.get(int(i["id"]), ""),
        )
        for i in view["items"]
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
    chips = _filter_chips_html(view, city_name=city_name)
    pager = _pagination_html(view, city_name=city_name, canonical_base=canonical_url)
    dock = render_generic_web_dock(
        base_url=base_url,
        surface="selection_page",
        city_id=int(view["city"]["id"]),
        city_name=city_name,
        telegram_url=cta_url,
    )
    body = hero + chips + note + places + pager + _share_html(share, venue_type="ice" if view.get("skating") else "shop") + dock
    elements = []
    for n, item in enumerate(view["items"]):
        slug = str(item.get("slug") or "").strip()
        path = place_path(city_name=city_name, slug=slug) if slug else f"/p/{int(item['id'])}"
        elements.append(
            {
                "@type": "ListItem",
                "position": n + 1,
                "name": item.get("name"),
                "url": join_public_origin(canonical_url, path),
            }
        )
    ld = json_for_script(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": share_title,
            "itemListElement": elements,
        }
    )
    page = _TEMPLATE_PATH.read_text(encoding="utf-8")
    city_link = f'<a href="{_esc(city_page_url)}">Весь лёд: {_esc(city_name)} сегодня</a>' if city_page_url else ""
    # ?t= и ?w= — та же подборка с фильтром. В индекс идёт только базовый /c/{город}.
    variant = bool(view.get("venue") or view.get("when"))
    page_no = int(view.get("page") or 1)
    lang, og_locale = html_lang_for_country(str(view["city"].get("country") or ""))
    return fill_placeholders(
        page,
        {
            "__OG_TITLE__": _esc(share_title),
            "__OG_DESCRIPTION__": _esc(share_description),
            "__CANONICAL__": _esc(canonical_url),
            "__OG_URL__": _esc(share["share_url"]),
            "__OG_IMAGE__": _esc(og_image_url),
            "__STORY_IMAGE__": _esc(story_image_url or og_image_url),
            "__LANG__": lang,
            "__OG_LOCALE__": og_locale,
            "__ROBOTS__": "noindex, follow" if (variant or page_no > 1) else "index, follow",
            "__HEAD_EXTRA__": _head_links_html(view, city_name=city_name, canonical_base=canonical_url),
            "__JSONLD__": ld,
            "__CITY__": _esc(city_name),
            "__CITY_LINK__": city_link,
            "__TRUST__": "<p>Расписание — с сайтов катков и от администраций; время и цену уточняйте на месте.</p>",
            "__BODY__": body,
        },
    )


def compose_selection_share(view: Mapping[str, Any], *, page_url: str) -> dict[str, str]:
    from src.application.client_share_message import share_body_for_native_share_dialog

    lines = [selection_share_title(view), selection_share_description(view)]
    for item, slots in selection_share_places(view)[:3]:
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
