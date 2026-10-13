"""
Публичная страница подборки ``/c/{город}?t=<тип>&w=<окно>`` (TASK-146).

То, чем делятся прямо из каталога: «Минск · где покататься на выходных», «Минск ·
магазины». Получатель видит ровно эту выборку — места, сеансы в окне с
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

from src.application.arena_profile import AMENITY_LABELS_RU
from src.application.arena_public_use_cases import (
    CITY_SELECTION_PAGE_SIZE,
    _CURRENT_SESSION_SQL,
    _OHM_SESSION_SQL,
    STATUS_ACTIVE,
    city_hockey_center_count,
    city_ohm_window_counts,
    city_selection_session_counts,
    city_selection_venue_types,
    list_city_ohm_places,
    list_city_selection_places,
    list_public_ice_arenas,
)
from src.application.ice_time_windows import resolve_window
from src.shared.copy_ru import t
from src.application.ice_city_day import city_slug, format_price_minor, plural_ru
from src.application.ice_time_windows import WHEN_KEYS
from src.application.place_links import catalog_start_param, join_public_origin, place_path, place_query
from src.application.place_page import absolute_day_label
from src.application.schedule_staleness import (
    LEVEL_STALE,
    load_arena_freshness,
    stale_note,
    staleness_level,
)
from src.shared.catalog_sharpening import SHARPENING_AMENITY_KEYS
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.notification_hours import NOTIFICATION_TZ
from src.shared.phone_guard import is_valid_public_phone, tel_href
from src.application.photo_cdn import visible_photo_url
from src.shared.public_display import (
    format_clock,
    format_public_name,
    format_street_address,
    session_day_phrase,
    short_day_word,
)
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
    "ice": t("route.skate"),
    "outdoor": "Уличный лёд",
    "shop": t("route.shops"),
    "gym": "Залы ОФП",
    "choreo": "Хореография",
    "pool": "Бассейны",
    "other": "Места для занятий",
    "ohm": t("chip.hockey"),
    "service": t("route.service"),
}

KIND_OHM = "ohm"
SEG_CENTERS = "centers"

SERVICE_AMENITY_KEYS: dict[str, tuple[str, ...]] = {
    "sharpening": SHARPENING_AMENITY_KEYS,
    "rental": ("skate_rental",),
    "service": SHARPENING_AMENITY_KEYS,
}

_SERVICE_LABELS = {
    "sharpening": "Заточка",
    "rental": "Прокат",
    "service": t("route.service"),
}

_OHM_SEG_KEYS = (
    ("today", "Сегодня"),
    ("tomorrow", "Завтра"),
    ("weekend", "Сб–Вс"),
    ("all", "Все"),
)

_NOUNS = {
    "shop": ("место", "места", "мест"),
    "service": ("место", "места", "мест"),
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


def clean_kind(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    return KIND_OHM if value == KIND_OHM else None


def clean_seg(raw: str | None) -> str | None:
    """``centers`` — центры по записи. Пусто и ``ohm`` — сеансы. Чужое значение отбрасываем."""
    value = (raw or "").strip().lower()
    return SEG_CENTERS if value == SEG_CENTERS else None


def clean_svc(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    return value if value in SERVICE_AMENITY_KEYS else None


def selection_path(
    *,
    city_name: str,
    venue: str | None,
    when: str | None,
    page: int | None = None,
    kind: str | None = None,
    svc: str | None = None,
    seg: str | None = None,
) -> str:
    params = {
        k: v
        for k, v in (("t", venue), ("w", when), ("kind", kind), ("seg", clean_seg(seg)), ("svc", svc))
        if v
    }
    if page is not None and int(page) > 1:
        params["page"] = str(int(page))
    return f"/c/{city_slug(city_name)}" + (("?" + urlencode(params)) if params else "")


def selection_image_path(
    *,
    city_name: str,
    venue: str | None,
    when: str | None,
    version: str | None = None,
    kind: str | None = None,
    svc: str | None = None,
    seg: str | None = None,
) -> str:
    """Путь картинки подборки. ``version`` — хэш данных: Telegram держит превью по URL."""
    params = {
        k: v
        for k, v in (("t", venue), ("w", when), ("kind", kind), ("seg", clean_seg(seg)), ("svc", svc))
        if v
    }
    if version:
        params["v"] = version
    return f"/c/{city_slug(city_name)}/og.png" + (("?" + urlencode(params)) if params else "")


async def _window_slots(
    session: AsyncSession,
    arena_ids: list[int],
    window: Mapping[str, Any] | None,
    now: datetime,
    *,
    session_sql: str = _CURRENT_SESSION_SQL,
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
                      AND {session_sql}
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


def _selection_session_totals(counts: Mapping[int, int]) -> tuple[int, int]:
    """``(сеансов, мест с сеансами)`` по всей подборке.

    Свежесть расписания на счёт не влияет: сеансы места с давним прогоном парсера
    показываем как обычно (решение владельца, TASK-243).
    """
    sessions = 0
    places = 0
    for n in counts.values():
        sessions += int(n)
        if int(n) > 0:
            places += 1
    return sessions, places


async def _apply_schedule_freshness(
    session: AsyncSession,
    items: list[Mapping[str, Any]],
    slots: dict[int, list[dict[str, Any]]],
    now: datetime,
) -> dict[int, str]:
    """Пометки свежести (TASK-180) для мест с сеансами. Сеансы не снимаем ни на каком уровне."""
    stale_notes: dict[int, str] = {}
    if not items:
        return stale_notes
    fresh = await load_arena_freshness(session, [int(i["id"]) for i in items], now=now)
    for item in items:
        aid = int(item["id"])
        if staleness_level(fresh.get(aid)) == LEVEL_STALE and slots.get(aid):
            stale_notes[aid] = stale_note(fresh.get(aid), now=now)
    return stale_notes


async def load_selection_view(
    session: AsyncSession,
    *,
    city: Mapping[str, Any],
    venue: str | None,
    when: str | None,
    page: int = 1,
    kind: str | None = None,
    svc: str | None = None,
    seg: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    page = clean_page(page)
    kind = clean_kind(kind)
    svc = clean_svc(svc)
    seg = clean_seg(seg)
    if seg == SEG_CENTERS:
        kind = KIND_OHM
    ohm = kind == KIND_OHM and not svc
    centers = ohm and seg == SEG_CENTERS
    service_mode = bool(svc)
    skating = (
        not service_mode
        and not centers
        and (ohm or venue is None or venue == "ice" or has_public_skating(venue))
    )
    window = None
    filter_chips: list[dict[str, Any]] = []
    facets: list[dict[str, Any]] = []
    total = 0
    pages = 1
    open_now_count = 0
    ohm_counts: dict[str, int] | None = None
    center_count: int | None = None
    if service_mode:
        catalog = await list_city_selection_places(
            session,
            city_id=int(city["id"]),
            venue_types=None,
            page=page,
            now=now,
            service_keys=SERVICE_AMENITY_KEYS[svc],
        )
        items = list(catalog.get("items") or [])
        total = int(catalog.get("total") or 0)
        pages = int(catalog.get("pages") or 1)
        open_now_count = int(catalog.get("open_now_count") or 0)
        venue = "service"
    elif centers:
        # Центр — место по записи, не сеанс: hockey_practice сюда не запрашиваем.
        offset = (page - 1) * MAX_PLACES
        listing = await list_public_ice_arenas(
            session,
            city_id=int(city["id"]),
            intent="ohm",
            hockey_segment="centers",
            limit=MAX_PLACES,
            cursor=str(offset) if offset else None,
        )
        items = list(listing.get("items") or [])
        total = int(listing.get("total") or 0)
        pages = max(1, (total + MAX_PLACES - 1) // MAX_PLACES)
        venue = KIND_OHM
        when = None
        center_count = total
    elif ohm:
        tw = resolve_window(when, now) if when else None
        if tw:
            window = tw.as_payload()
        catalog = await list_city_ohm_places(
            session,
            city_id=int(city["id"]),
            page=page,
            now=now,
            window=tw,
        )
        items = list(catalog.get("items") or [])
        total = int(catalog.get("total") or 0)
        pages = int(catalog.get("pages") or 1)
        venue = KIND_OHM
        ohm_counts = await city_ohm_window_counts(session, city_id=int(city["id"]), now=now)
        center_count = await city_hockey_center_count(session, city_id=int(city["id"]))
    elif when:
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
    session_sql = _OHM_SESSION_SQL if ohm else _CURRENT_SESSION_SQL
    slots = (
        await _window_slots(
            session, [int(i["id"]) for i in items], window, now, session_sql=session_sql
        )
        if skating
        else {}
    )
    # TASK-180: свежесть на момент ``now`` — см. ``_apply_schedule_freshness``.
    stale_notes: dict[int, str] = {}
    if skating and items:
        stale_notes = await _apply_schedule_freshness(session, items, slots, now)
    # В окне — только места, где в окне есть лёд; пусто — честно показываем ближайшее.
    window_empty = False
    if service_mode or centers:
        hits = items
        shown = items
    elif ohm:
        hits = [i for i in items if slots.get(int(i["id"]))]
        window_empty = bool(window) and not hits
        if window_empty:
            catalog = await list_city_ohm_places(
                session, city_id=int(city["id"]), page=page, now=now, window=None
            )
            items = list(catalog.get("items") or [])
            total = int(catalog.get("total") or 0)  # иначе в описании «0 катков» при непустом списке
            pages = int(catalog.get("pages") or 1)
            slots = await _window_slots(
                session,
                [int(i["id"]) for i in items],
                None,
                now,
                session_sql=session_sql,
            )
            stale_notes = await _apply_schedule_freshness(session, items, slots, now)
            hits = [i for i in items if slots.get(int(i["id"]))]
        shown = hits or items
    else:
        hits = [i for i in items if slots.get(int(i["id"]))] if window else items
        window_empty = bool(window) and not hits
        if window_empty and skating:
            # В окне пусто — ближайшие сеансы теми же билетами, а не строкой из API.
            slots = await _window_slots(
                session, [int(i["id"]) for i in items], None, now, session_sql=session_sql
            )
            stale_notes = await _apply_schedule_freshness(session, items, slots, now)
            nearest = [i for i in items if slots.get(int(i["id"]))]
            # Сначала места с ближайшим льдом — по времени первого сеанса.
            nearest.sort(
                key=lambda i: (
                    str(slots[int(i["id"])][0].get("local_date") or ""),
                    str(slots[int(i["id"])][0].get("starts_at_local") or ""),
                    int(i["id"]),
                )
            )
            items = nearest + [i for i in items if not slots.get(int(i["id"]))]
        shown = hits or items
    shown_page = shown[:MAX_PLACES] if not service_mode else shown
    # Счёт для превью — по всей подборке, а не по странице: один агрегат вместо len(shown_page).
    if ohm:
        session_total = sum(len(slots.get(int(i["id"]), [])) for i in shown_page)
        window_places = 0
    else:
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
        session_total, window_places = _selection_session_totals(selection_counts)
    out: dict[str, Any] = {
        "city": dict(city),
        "venue": venue,
        "when": when,
        "kind": kind,
        "svc": svc,
        "seg": SEG_CENTERS if centers else None,
        "page": page,
        "pages": pages,
        "total": total,
        "filter_chips": filter_chips,
        "window": window,
        "window_empty": window_empty,
        "items": shown_page,
        "slots": slots,
        "stale_notes": stale_notes,
        "skating": skating,
        "session_count": session_total,
        # Места с сеансом в окне — по всей выборке: это число обещает заголовок.
        "window_places": window_places,
        # Фасеты всего города: по ним выбирается слово «катков»/«мест», а не по странице.
        "venue_type_facets": facets,
    }
    if ohm_counts is not None:
        out["ohm_counts"] = ohm_counts
    if center_count is not None:
        out["center_count"] = center_count
    if service_mode:
        out["open_now_count"] = open_now_count
        out["service_filter_keys"] = SERVICE_AMENITY_KEYS[svc]
    return out


def selection_title(view: Mapping[str, Any]) -> str:
    city = str(view["city"]["name"])
    svc = view.get("svc")
    if svc:
        return f"{city} · {_SERVICE_LABELS.get(str(svc), _TOPIC['service']).lower()}"
    if view.get("kind") == KIND_OHM:
        window = view.get("window")
        if window:
            return f"{city} · {t('chip.hockey').lower()} — {str(window['label']).lower()}"
        return f"{city} · {t('chip.hockey').lower()}"
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
    svc = view.get("svc")
    if svc:
        return f"{city} · {_SERVICE_LABELS.get(str(svc), _TOPIC['service']).lower()}"
    if view.get("kind") == KIND_OHM:
        window = view.get("window")
        if window:
            phrase = absolute_window_phrase(window)
            if phrase:
                return f"{city} · {t('chip.hockey').lower()} — {phrase}"
        return f"{city} · {t('chip.hockey').lower()}"
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
    if view.get("seg") == SEG_CENTERS:
        return ("центр", "центра", "центров")
    if view.get("kind") == KIND_OHM:
        return ("каток", "катка", "катков")
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
    svc = view.get("svc")
    if svc:
        n = int(view.get("total") or 0)
        noun = selection_count_noun(view)
        k = int(view.get("open_now_count") or 0)
        head = f"{n} {plural_ru(n, *noun)}"
        # Ночью «0 открыты сейчас» — шум: статус каждого места и так на карточке.
        if not k:
            return head
        return f"{head} · {k} {plural_ru(k, 'открыто', 'открыты', 'открыты')} сейчас"
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
    from src.application.place_card_image import selection_story_board

    board = selection_story_board(view)
    raw = "|".join(
        (
            str(selection_place_count(view)),
            str(int(view.get("session_count") or 0)),
            _minsk_day().isoformat(),
            str(board.get("headline") or ""),
            str(len(board.get("rows") or [])),
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


def selection_start_param(
    *,
    city_id: int,
    venue: str | None,
    when: str | None,
    kind: str | None = None,
    svc: str | None = None,
) -> str:
    """startapp с тем же типом места и окном, что на странице подборки."""
    if clean_svc(svc):
        return catalog_start_param(int(city_id), "service", None)
    if clean_kind(kind) == KIND_OHM:
        return catalog_start_param(int(city_id), KIND_OHM, when)
    if venue == "service":
        return catalog_start_param(int(city_id), "service", None)
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


def _selection_where(item: Mapping[str, Any], *, city_name: str) -> str:
    district = str(item.get("district") or "").strip()
    street = format_street_address(str(item.get("address") or ""), city=city_name)
    return " · ".join(x for x in (district, street) if x)


def _place_photo_url(item: Mapping[str, Any]) -> str | None:
    """Тот же кадр, что в мини-карточке. Нет опубликованного — карточка без фото."""
    for key in ("card", "thumb"):
        url = visible_photo_url(str(item.get(key) or ""))
        if url:
            return url
    return None


def _yandex_maps_href(item: Mapping[str, Any]) -> str | None:
    lat, lon = item.get("latitude"), item.get("longitude")
    if lat is not None and lon is not None:
        return f"https://yandex.ru/maps/?pt={float(lon)},{float(lat)}&z=16&l=map"
    return None


def _ohm_seg_html(view: Mapping[str, Any], *, city_name: str) -> str:
    counts = view.get("ohm_counts") or {}
    active = str(view.get("when") or "all")
    parts: list[str] = []
    for key, label in _OHM_SEG_KEYS:
        n = int(counts.get(key, 0) or 0)
        inner = f"{_esc(label)} <small>{n}</small>"
        if key == active or (key == "all" and not view.get("when")):
            parts.append(f'<span class="on">{inner}</span>')
        elif n <= 0:
            parts.append(f'<span class="off">{inner}</span>')
        else:
            when = key if key != "all" else None
            href = selection_path(city_name=city_name, venue=None, when=when, kind=KIND_OHM)
            parts.append(f'<a href="{_esc(href)}">{inner}</a>')
    return '<nav class="seg" aria-label="Когда">' + "".join(parts) + "</nav>"


def _ohm_rule_html() -> str:
    return (
        '<p class="rule"><b>Любительский хоккей:</b> полная экипировка, детям — шлем с маской. '
        "Записи нет — билет в кассе катка.</p>"
    )


def _centers_rule_html() -> str:
    return '<p class="rule">По записи, не сеанс.</p>'


def _hockey_segment_chips_html(view: Mapping[str, Any], *, city_name: str) -> str:
    """ОХМ и Центры — те же чипы, что у услуг и типов мест. Подписей на чипах нет."""
    centers = view.get("seg") == SEG_CENTERS
    if not centers and not int(view.get("center_count") or 0):
        # Город без центров: чип «Центры» вёл бы в пустой список.
        return ""
    ohm_href = selection_path(
        city_name=city_name,
        venue=None,
        when=None if centers else view.get("when"),
        kind=KIND_OHM,
    )
    centers_href = selection_path(
        city_name=city_name, venue=None, when=None, kind=KIND_OHM, seg=SEG_CENTERS
    )
    count = view.get("center_count")
    centers_label = "Центры" if count is None else f"Центры <small>{int(count)}</small>"
    ohm_cls = "chip" + ("" if centers else " chip--on")
    centers_cls = "chip" + (" chip--on" if centers else "")
    return (
        f'<nav class="chips" aria-label="{_esc(t("chip.hockey"))}">'
        f'<a class="{ohm_cls}" href="{_esc(ohm_href)}">ОХМ</a>'
        f'<a class="{centers_cls}" href="{_esc(centers_href)}">{centers_label}</a>'
        "</nav>"
    )


def _service_chips_html(view: Mapping[str, Any], *, city_name: str) -> str:
    active = str(view.get("svc") or "service")
    chips = [
        ("sharpening", "Заточка"),
        ("rental", "Прокат"),
    ]
    parts: list[str] = []
    for key, label in chips:
        href = selection_path(city_name=city_name, venue=None, when=None, svc=key)
        cls = "chip" + (" chip--on" if active == key else "")
        parts.append(f'<a class="{cls}" href="{_esc(href)}">{_esc(label)}</a>')
    all_href = selection_path(city_name=city_name, venue=None, when=None)
    parts.append(f'<a class="chip" href="{_esc(all_href)}">Все места</a>')
    return '<nav class="chips" aria-label="Услуга">' + "".join(parts) + "</nav>"


def _place_html(
    item: Mapping[str, Any],
    *,
    city_name: str,
    slots: list[dict[str, Any]],
    stale: str = "",
    more_anchor: str = "schedule",
    service_mode: bool = False,
    service_highlight_keys: frozenset[str] | None = None,
) -> str:
    today = datetime.now(ZoneInfo("Europe/Minsk")).date()
    slug = str(item.get("slug") or "")
    href = place_path(city_name=city_name, slug=slug) if slug else ""
    where = _selection_where(item, city_name=city_name)
    chips = ""
    rest = len(slots) - MAX_SLOTS_PER_PLACE
    for s in slots[:MAX_SLOTS_PER_PLACE]:
        hhmm = str(s.get("starts_at_local") or "")[:5]
        day = s.get("local_date")
        if hasattr(day, "year"):
            phrase = session_day_phrase(day, hhmm, today=today)
        else:
            phrase = hhmm
        price = format_price_minor(
            s.get("price_adult_minor") if s.get("price_adult_minor") is not None else s.get("price_minor"),
            str(s.get("currency_code") or "BYN"),
        )
        basis_cls = public_basis_css_class(str(s.get("schedule_basis") or "live"))
        slot_cls = "slot" + (f" {basis_cls}" if basis_cls else "")
        slot_inner = (
            f'<span class="slot__time">{_esc(phrase)}</span>'
            + (f'<span class="slot__price">{_esc(price)}</span>' if price else "")
        )
        if href:
            chips += (
                f'<a class="{_esc(slot_cls)}" href="{_esc(href + place_query(session_id=int(s["id"])))}">'
                f"{slot_inner}</a>"
            )
        else:
            chips += f'<span class="{_esc(slot_cls)}">{slot_inner}</span>'
    if rest > 0 and href:
        chips += f'<a class="slot slot--more" href="{_esc(href)}#{_esc(more_anchor)}">ещё {rest}</a>'
    raw_line = str(item.get("live_line") or "").strip()
    line = "" if chips or not raw_line else f'<p class="muted">{_esc(raw_line)}</p>'
    # TASK-180: > 6 ч — сеансы показываем, но над ними спокойная строка «могло измениться».
    stale_html = f'<p class="pick__stale">{_esc(stale)}</p>' if stale and chips else ""
    photo = _place_photo_url(item)
    name = _esc(format_public_name(str(item.get("name") or "")))
    name_html = f'<a href="{_esc(href)}">{name}</a>' if href else name
    if photo and href:
        media = (
            f'<a class="pick__media" href="{_esc(href)}" data-icon="{_esc(str(item.get("venue_type") or ""))}">'
            f'<img class="pick__photo" src="{_esc(photo)}" alt="" loading="lazy" decoding="async" />'
            f"</a>"
        )
    elif photo:
        media = (
            f'<span class="pick__media" data-icon="{_esc(str(item.get("venue_type") or ""))}">'
            f'<img class="pick__photo" src="{_esc(photo)}" alt="" loading="lazy" decoding="async" />'
            f"</span>"
        )
    else:
        from src.application.catalog_icons import icon_svg

        mark = icon_svg({"ice": "skate", "outdoor": "skate", "shop": "shop"}.get(str(item.get("venue_type") or "ice"), "person"))
        media = f'<span class="pick__icon" aria-hidden="true">{mark}</span>' if mark else ""
    if service_mode:
        vtype = str(item.get("venue_type") or "ice")
        pick_cls = "sec pick" + (" pick--rink" if vtype in ("ice", "outdoor") else "")
        open_st = item.get("open_state") if isinstance(item.get("open_state"), Mapping) else {}
        state = str(open_st.get("state") or "unknown")
        olabel = str(open_st.get("label") or "")
        rink_note = ' <small class="muted">· каток</small>' if vtype in ("ice", "outdoor") else ""
        open_html = (
            f'<span class="pick__open pick__open--{_esc(state)}">{_esc(olabel)}</span>' if olabel else ""
        )
        highlight = service_highlight_keys or frozenset()
        amenity_keys = list(item.get("amenity_keys") or [])
        svc_bits = ""
        for key in amenity_keys:
            label = AMENITY_LABELS_RU.get(key, key)
            cls = "hl" if key in highlight else ""
            svc_bits += f'<span class="{_esc(cls)}">{_esc(label)}</span>'
        phone = str(item.get("phone") or "").strip()
        call = ""
        if phone and is_valid_public_phone(phone):
            call = f'<a href="tel:{_esc(tel_href(phone))}">Позвонить</a>'
        else:
            call = "<span>Позвонить</span>"
        route_href = _yandex_maps_href(item)
        route = (
            f'<a href="{_esc(route_href)}" rel="noopener">Маршрут</a>'
            if route_href
            else "<span>Маршрут</span>"
        )
        return (
            f'<section class="{pick_cls}">'
            '<div class="pick__head">'
            + media
            + '<div class="pick__titles">'
            + f'<h2 class="pick__name">{name_html}'
            + rink_note
            + open_html
            + "</h2>"
            + (f'<p class="pick__where">{_esc(where)}</p>' if where else "")
            + "</div></div>"
            + (f'<div class="svc">{svc_bits}</div>' if svc_bits else "")
            + f'<div class="act">{call}{route}</div>'
            + "</section>"
        )
    return (
        '<section class="sec pick">'
        '<div class="pick__head">'
        + media
        + '<div class="pick__titles">'
        + f'<h2 class="pick__name">{name_html}</h2>'
        + (f'<p class="pick__where">{_esc(where)}</p>' if where else "")
        + "</div></div>"
        + (stale_html + f'<div class="slots">{chips}</div>' if chips else line)
        + "</section>"
    )


def _center_card_html(item: Mapping[str, Any], *, city_name: str) -> str:
    """Карточка центра: вся карточка — ссылка на страницу места. Без сеанса, цены и кнопок."""
    slug = str(item.get("slug") or "").strip()
    href = str(item.get("public_path") or "").strip()
    if not href and slug:
        href = place_path(city_name=city_name, slug=slug)
    where = _selection_where(item, city_name=city_name)
    badge = str(item.get("center_badge") or "").strip()
    live = item.get("live") if isinstance(item.get("live"), Mapping) else {}
    line = ""
    if str(live.get("kind") or "") != "session":
        line = str(live.get("text") or item.get("live_line") or "").strip()
    photo = _place_photo_url(item)
    name = _esc(format_public_name(str(item.get("name") or "")))
    if photo:
        media = (
            f'<span class="pick__media" data-icon="{_esc(str(item.get("venue_type") or ""))}">'
            f'<img class="pick__photo" src="{_esc(photo)}" alt="" loading="lazy" decoding="async" />'
            f"</span>"
        )
    else:
        from src.application.catalog_icons import icon_svg

        mark = icon_svg({"ice": "skate", "outdoor": "skate", "shop": "shop"}.get(str(item.get("venue_type") or "ice"), "person"))
        media = f'<span class="pick__icon" aria-hidden="true">{mark}</span>' if mark else ""
    badge_html = f'<span class="badge">{_esc(badge)}</span>' if badge else ""
    line_html = f'<p class="pick__line">{_esc(line)}</p>' if line else ""
    inner = (
        '<div class="pick__head">'
        + media
        + '<div class="pick__titles">'
        + f'<h2 class="pick__name">{name}</h2>'
        + (f'<p class="pick__where">{_esc(where)}</p>' if where else "")
        + "</div></div>"
        + badge_html
        + line_html
    )
    if href:
        return f'<a class="sec pick" href="{_esc(href)}">{inner}</a>'
    return f'<section class="sec pick">{inner}</section>'


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
    venue, when, kind, svc = view.get("venue"), view.get("when"), view.get("kind"), view.get("svc")
    seg = view.get("seg")
    path_venue = None if kind == KIND_OHM or svc else venue
    prev_href = (
        selection_path(
            city_name=city_name, venue=path_venue, when=when, kind=kind, svc=svc, seg=seg, page=page - 1
        )
        if page > 1
        else None
    )
    next_href = (
        selection_path(
            city_name=city_name, venue=path_venue, when=when, kind=kind, svc=svc, seg=seg, page=page + 1
        )
        if page < pages
        else None
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
    venue, when, kind, svc = view.get("venue"), view.get("when"), view.get("kind"), view.get("svc")
    seg = view.get("seg")
    path_venue = None if kind == KIND_OHM or svc else venue
    links = []
    if page > 1:
        prev = selection_path(
            city_name=city_name, venue=path_venue, when=when, kind=kind, svc=svc, seg=seg, page=page - 1
        )
        links.append(f'<link rel="prev" href="{_esc(join_public_origin(canonical_base, prev))}" />')
    if page < pages:
        nxt = selection_path(
            city_name=city_name, venue=path_venue, when=when, kind=kind, svc=svc, seg=seg, page=page + 1
        )
        links.append(f'<link rel="next" href="{_esc(join_public_origin(canonical_base, nxt))}" />')
    return "".join(links)


def _hero_kicker(view: Mapping[str, Any]) -> str:
    """Пояснение раздела — один раз под заголовком, не на кнопке."""
    if view.get("kind") == KIND_OHM:
        if view.get("seg") == SEG_CENTERS:
            return "центры по записи"
        return t("route.hockey.hint")
    svc = str(view.get("svc") or "")
    if svc == "rental":
        return "прокат коньков"
    if svc:
        return t("route.service.hint")
    if view.get("venue") == "ice":
        return t("selection.ice.hint")
    window = view.get("window") or {}
    return str(window.get("label") or "") or "Подборка"


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
    city_name = str(view["city"]["name"])
    title = selection_title(view)
    share_title = selection_share_title(view)
    description = selection_description(view)
    share_description = selection_share_description(view)
    note = (
        f'<p class="b-rule">{_esc(view["window"]["label"])}: сеансов нет — показываем ближайшие.</p>'
        if view.get("window_empty")
        else ""
    )
    stale_notes = view.get("stale_notes") or {}
    service_mode = bool(view.get("svc"))
    centers_mode = view.get("seg") == SEG_CENTERS
    highlight = frozenset(view.get("service_filter_keys") or ())
    more_anchor = "ohm" if view.get("kind") == KIND_OHM else "schedule"
    if centers_mode:
        places = "".join(_b_center_card(i, city_name=city_name) for i in view["items"])
    else:
        places = "".join(
            _b_place_card(
                i,
                city_name=city_name,
                slots=view["slots"].get(int(i["id"]), []),
                more_anchor=more_anchor,
                service_mode=service_mode,
                service_highlight_keys=highlight,
            )
            for i in view["items"]
        )
    if not places:
        if service_mode:
            empty = "Пока не знаем мест с заточкой или прокатом в этом городе."
        elif centers_mode:
            empty = "Центров по записи нет"
        elif view.get("kind") == KIND_OHM:
            empty = "Пока нет сеансов ОХМ в этом городе."
        else:
            empty = "В этой подборке пока пусто — загляните в каталог."
        places = f'<p class="b-text">{_esc(empty)}</p>'
    from src.application.style_b import back_pill, brand_link, hero_html, share_html

    hero = hero_html(
        title=_b_list_title(view),
        kicker=_hero_kicker(view),
        sub_html=_esc(description),
        bar_html=back_pill(f"/c/{city_slug(city_name)}", format_public_name(city_name)) + brand_link(end=True),
        variant="list",
    )
    controls = _b_controls(view, city_name=city_name)
    from src.application.catalog_list_share import (
        catalog_list_share_tail,
        catalog_selection_share_button,
        selection_share_endpoint,
    )

    share_pick = ""
    if not service_mode and not centers_mode and view.get("items"):
        share_pick = catalog_selection_share_button(endpoint=selection_share_endpoint(view))
    need_share_js = bool(share_pick) or any((view.get("slots") or {}).values())
    body = (
        hero
        + (f'<section class="b-sec">{controls}</section>' if controls else "")
        + (f'<section class="b-sec">{note}</section>' if note else "")
        + f'<section class="b-sec b-cards">{places}</section>'
        + _b_pager(view, city_name=city_name)
        + share_pick
        + share_html(share, telegram_url=cta_url, story_image_url=story_image_url or og_image_url, telegram_link_only=True)
    )
    elements = []
    for item in view["items"]:
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue
        path = place_path(city_name=city_name, slug=slug)
        elements.append(
            {
                "@type": "ListItem",
                "position": len(elements) + 1,
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
    from src.application.style_b import STYLE_VERSION, TOKENS_VERSION

    page = _B_TEMPLATE_PATH.read_text(encoding="utf-8")
    city_link = (
        f'<a href="{_esc(city_page_url)}">Весь лёд: {_esc(format_public_name(city_name))} сегодня</a>'
        if city_page_url
        else ""
    )
    # ?t= и ?w= — та же подборка с фильтром. В индекс идёт только базовый /c/{город}.
    variant = bool(view.get("venue") or view.get("when") or view.get("svc"))
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
            "__LANG__": lang,
            "__OG_LOCALE__": og_locale,
            "__ROBOTS__": "noindex, follow" if (variant or page_no > 1) else "index, follow",
            "__HEAD_EXTRA__": _head_links_html(view, city_name=city_name, canonical_base=canonical_url),
            "__JSONLD__": ld,
            "__TOKENS_V__": TOKENS_VERSION,
            "__STYLE_V__": STYLE_VERSION,
            "__CITY_LINK__": city_link,
            "__BODY__": body,
            **catalog_list_share_tail(scripts=need_share_js, css=bool(share_pick)),
        },
    )


def compose_selection_share(view: Mapping[str, Any], *, page_url: str) -> dict[str, str]:
    from src.application.client_share_message import share_body_for_native_share_dialog
    from src.application.place_card_image import selection_story_board

    board = selection_story_board(view)
    lines = [selection_share_title(view), selection_share_description(view)]
    # Тот же срез, что на story.png. Подпись «Сегодня вечером» нужна только когда
    # есть сеансы; без льда заголовок уже равен строке со счётом мест.
    if board["text_cta"]:
        lines.append(str(board["headline"]))
    cap = 6 if view.get("skating") else 3
    shown = board["rows"][:cap]
    for name, when in shown:
        lines.append(f"• {name} — {when}" if when else f"• {name}")
    hidden = len(board["rows"]) - len(shown)
    if hidden:
        lines.append(f"и ещё {hidden} — по ссылке")
    if board["note"]:
        lines.append(str(board["note"]))
    if board["text_cta"]:
        lines.append(str(board["text_cta"]))
    text_value = page_url + "\n\n" + "\n".join(lines)
    return {
        "share_url": page_url,
        "share_text": text_value,
        "share_body": share_body_for_native_share_dialog(text_value, page_url),
    }


# ── TASK-246 · стиль B для списков /c/{город}?… ─────────────────────────────────

_B_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "b.html"


def _selection_thumb_img_attrs(item: Mapping[str, Any]) -> tuple[str | None, str]:
    """Квадрат 64×64 CSS (128×128 @2x): ``src`` — thumb, иначе card; ``srcset`` только если слот >128px."""
    thumb = visible_photo_url(str(item.get("thumb") or ""))
    card = visible_photo_url(str(item.get("card") or ""))
    src = thumb or card
    if not src:
        return None, ""
    if thumb and card and thumb != card:
        return src, (
            f' srcset="{_esc(thumb)} 320w, {_esc(card)} 800w"'
            ' sizes="(min-width: 641px) 128px, 64px"'
        )
    return src, ""


def _b_thumb(item: Mapping[str, Any], *, href: str) -> str:
    from src.application.catalog_icons import rink_motif_svg

    photo, extra = _selection_thumb_img_attrs(item)
    inner = (
        f'<img src="{_esc(photo)}"{extra} alt="" loading="lazy" decoding="async" width="128" height="128" />'
        if photo
        else rink_motif_svg(small=True)
    )
    if href:
        return f'<a class="b-card2__thumb" href="{_esc(href)}" tabindex="-1" aria-hidden="true">{inner}</a>'
    return f'<span class="b-card2__thumb" aria-hidden="true">{inner}</span>'


def _b_card_head(item: Mapping[str, Any], *, city_name: str, href: str, extra: str = "") -> str:
    name = _esc(format_public_name(str(item.get("name") or "")))
    name_html = f'<a href="{_esc(href)}">{name}</a>' if href else name
    where = _selection_where(item, city_name=city_name)
    where_html = f'<span class="b-card2__where">{_esc(where)}</span>' if where else ""
    return (
        f'<div class="b-card2__head">{_b_thumb(item, href=href)}'
        f'<div class="b-card2__titles"><h2 class="b-card2__name">{name_html}</h2>{where_html}{extra}</div></div>'
    )


# Строки состояния из ленты, которые говорят факт. «Расписание уточняется» (kind unknown) —
# оговорка: на сайте её нет (решение владельца, craft-guide), карточка просто без строки.
_B_FACT_LIVE_KINDS = frozenset({"phone", "season_closed", "closed", "place"})


def _b_state_note(item: Mapping[str, Any]) -> str:
    live = item.get("live") if isinstance(item.get("live"), Mapping) else {}
    if str(live.get("kind") or "") not in _B_FACT_LIVE_KINDS:
        return ""
    return str(live.get("text") or "").strip()


def _b_place_card(
    item: Mapping[str, Any],
    *,
    city_name: str,
    slots: list[dict[str, Any]],
    more_anchor: str,
    service_mode: bool,
    service_highlight_keys: frozenset[str],
) -> str:
    from src.application.catalog_icons import icon_svg

    today = datetime.now(ZoneInfo("Europe/Minsk")).date()
    slug = str(item.get("slug") or "")
    href = place_path(city_name=city_name, slug=slug) if slug else ""
    if service_mode:
        open_st = item.get("open_state") if isinstance(item.get("open_state"), Mapping) else {}
        state = str(open_st.get("state") or "unknown")
        label = str(open_st.get("label") or "")
        extra = f'<span class="b-open b-open--{_esc(state)}"><i></i>{_esc(label)}</span>' if label else ""
        chips = "".join(
            f'<span class="b-chip{" b-chip--hl" if key in service_highlight_keys else ""}">'
            f"{_esc(AMENITY_LABELS_RU.get(key, key))}</span>"
            for key in list(item.get("amenity_keys") or [])
        )
        buttons: list[str] = []
        phone = str(item.get("phone") or "").strip()
        if phone and is_valid_public_phone(phone):
            buttons.append(f'<a class="b-btn" href="tel:{_esc(tel_href(phone))}">{icon_svg("phone")}Позвонить</a>')
        route_href = _yandex_maps_href(item)
        if route_href:
            buttons.append(f'<a class="b-btn" href="{_esc(route_href)}" rel="noopener">{icon_svg("route")}Маршрут</a>')
        return (
            '<article class="b-card2">'
            + _b_card_head(item, city_name=city_name, href=href, extra=extra)
            + (f'<div class="b-chips">{chips}</div>' if chips else "")
            + (f'<div class="b-btns">{"".join(buttons)}</div>' if buttons else "")
            + "</article>"
        )
    tickets: list[str] = []
    for s in slots[:MAX_SLOTS_PER_PLACE]:
        day = s.get("local_date")
        clock = format_clock(str(s.get("starts_at_local") or ""))
        word = short_day_word(day, today=today) if hasattr(day, "year") else ""
        price = format_price_minor(
            s.get("price_adult_minor") if s.get("price_adult_minor") is not None else s.get("price_minor"),
            str(s.get("currency_code") or "BYN"),
        )
        inner = (
            (f'<span class="b-slot__day">{_esc(word)}</span>' if word else "")
            + f'<b class="b-slot__time">{_esc(clock)}</b>'
            + (f'<span class="b-slot__price">{_esc(price)}</span>' if price else "")
        )
        if href:
            tickets.append(
                f'<a class="b-slot" href="{_esc(href + place_query(session_id=int(s["id"])))}">{inner}</a>'
            )
        else:
            tickets.append(f'<span class="b-slot">{inner}</span>')
    rest = len(slots) - MAX_SLOTS_PER_PLACE
    if rest > 0 and href:
        tickets.append(f'<a class="b-slot b-slot--more" href="{_esc(href)}#{_esc(more_anchor)}">ещё {rest}</a>')
    note = _b_state_note(item)
    body = (
        f'<div class="b-slots">{"".join(tickets)}</div>'
        if tickets
        else (f'<p class="b-note">{_esc(note)}</p>' if note else "")
    )
    card = '<article class="b-card2">' + _b_card_head(item, city_name=city_name, href=href) + body + "</article>"
    if not slots or not href:
        return card
    first = slots[0]
    sid = first.get("id")
    if sid is None:
        return card
    from src.application.catalog_list_share import catalog_invite_link, invite_label_for_slot

    place_name = format_public_name(str(item.get("name") or ""))
    label = invite_label_for_slot(first, today=today)
    invite_href = href + place_query(session_id=int(sid))
    invite = catalog_invite_link(
        arena_ref=int(item["id"]),
        session_id=int(sid),
        invite_label=label,
        place_name=place_name,
        fallback_href=invite_href,
    )
    return f'<div class="b-card2-wrap">{invite}{card}</div>'


def _b_center_card(item: Mapping[str, Any], *, city_name: str) -> str:
    slug = str(item.get("slug") or "").strip()
    href = str(item.get("public_path") or "").strip() or (place_path(city_name=city_name, slug=slug) if slug else "")
    badge = str(item.get("center_badge") or "").strip()
    live = item.get("live") if isinstance(item.get("live"), Mapping) else {}
    line = _b_state_note(item)
    extra = (f'<span class="b-chip b-chip--sm">{_esc(badge)}</span>' if badge else "") + (
        f'<span class="b-card2__where">{_esc(line)}</span>' if line else ""
    )
    return '<article class="b-card2">' + _b_card_head(item, city_name=city_name, href=href, extra=extra) + "</article>"


def _b_chips_nav(items: list[tuple[str, str, bool]], *, label: str) -> str:
    """Чипы-переключатели: (подпись с разметкой, href, активен)."""
    parts = []
    for text_html, href, on in items:
        cls = "b-toggle b-toggle--on" if on else "b-toggle"
        parts.append(f'<a class="{cls}" href="{_esc(href)}">{text_html}</a>')
    return f'<nav class="b-toggles" aria-label="{_esc(label)}">{"".join(parts)}</nav>'


def _b_controls(view: Mapping[str, Any], *, city_name: str) -> str:
    out = ""
    kind = view.get("kind")
    if kind == KIND_OHM:
        centers = view.get("seg") == SEG_CENTERS
        if centers or int(view.get("center_count") or 0):
            count = view.get("center_count")
            centers_label = "Центры" if count is None else f"Центры <small>{int(count)}</small>"
            out += _b_chips_nav(
                [
                    ("ОХМ", selection_path(city_name=city_name, venue=None, when=None if centers else view.get("when"), kind=KIND_OHM), not centers),
                    (centers_label, selection_path(city_name=city_name, venue=None, when=None, kind=KIND_OHM, seg=SEG_CENTERS), centers),
                ],
                label=t("chip.hockey"),
            )
        if not centers:
            counts = view.get("ohm_counts") or {}
            active = str(view.get("when") or "all")
            parts = []
            for key, label in _OHM_SEG_KEYS:
                n = int(counts.get(key, 0) or 0)
                label = t("when.weekend") if key == "weekend" else label
                inner = f"{_esc(label)} <small>{n if n else '—'}</small>"
                if key == active:
                    parts.append(f'<span class="b-toggle b-toggle--on" aria-current="true">{inner}</span>')
                elif n <= 0:
                    parts.append(f'<span class="b-toggle b-toggle--off">{inner}</span>')
                else:
                    when = key if key != "all" else None
                    href = selection_path(city_name=city_name, venue=None, when=when, kind=KIND_OHM)
                    parts.append(f'<a class="b-toggle" href="{_esc(href)}">{inner}</a>')
            out += f'<nav class="b-toggles" aria-label="Когда">{"".join(parts)}</nav>'
            out += (
                '<p class="b-rule"><b>Любительский хоккей:</b> полная экипировка, детям — шлем с маской. '
                "Записи нет — билет в кассе катка.</p>"
            )
        else:
            out += '<p class="b-rule">По записи, не сеанс.</p>'
        return out
    if view.get("svc"):
        active = str(view.get("svc") or "service")
        items = [
            (
                _esc(label),
                selection_path(city_name=city_name, venue=None, when=None, svc=key),
                key == active or (key == "sharpening" and active == "service"),
            )
            for key, label in (("sharpening", "Заточка"), ("rental", "Прокат"))
        ]
        items.append(("Все места", selection_path(city_name=city_name, venue=None, when=None), False))
        return _b_chips_nav(items, label="Услуга")
    chips = list(view.get("filter_chips") or [])
    if chips and not view.get("when"):
        active = str(view.get("venue") or "")
        items = [("Все", selection_path(city_name=city_name, venue=None, when=None, page=1), not active)]
        for chip in chips:
            key = str(chip.get("key") or "")
            items.append(
                (_esc(str(chip.get("label") or key)), selection_path(city_name=city_name, venue=key, when=None, page=1), active == key)
            )
        return _b_chips_nav(items, label="Тип места")
    return ""


def _b_pager(view: Mapping[str, Any], *, city_name: str) -> str:
    pages = int(view.get("pages") or 1)
    page = int(view.get("page") or 1)
    if pages <= 1:
        return ""
    venue, when, kind, svc, seg = view.get("venue"), view.get("when"), view.get("kind"), view.get("svc"), view.get("seg")
    path_venue = None if kind == KIND_OHM or svc else venue

    def href(n: int) -> str:
        return selection_path(city_name=city_name, venue=path_venue, when=when, kind=kind, svc=svc, seg=seg, page=n)

    prev = f'<a class="b-btn" rel="prev" href="{_esc(href(page - 1))}">Назад</a>' if page > 1 else ""
    nxt = f'<a class="b-btn" rel="next" href="{_esc(href(page + 1))}">Дальше</a>' if page < pages else ""
    return (
        f'<nav class="b-sec" aria-label="Страницы"><p class="b-note">Страница {page} из {pages}</p>'
        f'<div class="b-btns">{prev}{nxt}</div></nav>'
    )


def _b_list_title(view: Mapping[str, Any]) -> str:
    """Заголовок раздела без города: город — в пилюле «‹ Минск»."""
    if view.get("kind") == KIND_OHM:
        return t("chip.hockey")
    svc = str(view.get("svc") or "")
    if svc == "rental":
        return "Прокат"
    if svc:
        return t("route.service")
    venue = str(view.get("venue") or "")
    if venue == "shop":
        return t("route.shops")
    if venue == "ice":
        return t("route.skate")
    window = view.get("window") or {}
    return str(window.get("label") or "") or "Места"
